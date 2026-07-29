"""Tests for low-traffic coordinated polling and error isolation."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ServiceValidationError
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.groupalarm_ha_connect.api import (
    GroupAlarmAlarmPage,
    GroupAlarmAuthenticationError,
    GroupAlarmClient,
    GroupAlarmError,
    GroupAlarmPermissionError,
    GroupAlarmRateLimitError,
    GroupAlarmRequestError,
    GroupAlarmResponseError,
    GroupAlarmServerError,
    GroupAlarmTransportError,
    GroupAlarmUser,
)
from custom_components.groupalarm_ha_connect.button import (
    BUTTONS,
    GroupAlarmFeedbackButton,
    _action_exception_key,
)
from custom_components.groupalarm_ha_connect.const import (
    CONF_FEEDBACK_DEVICE_ID,
    CONF_ORGANIZATION_DURATIONS,
    CONF_ORGANIZATION_IDS,
    CONF_ORGANIZATION_NAMES,
    CONF_USER_ID,
    DOMAIN,
    MAX_PARALLEL_ORGANIZATIONS,
)
from custom_components.groupalarm_ha_connect.coordinator import (
    GroupAlarmCoordinator,
    _classify_error,
)
from custom_components.groupalarm_ha_connect.feedback import (
    FeedbackActionError,
    FeedbackBusyError,
    FeedbackConfigurationError,
    FeedbackConflictError,
    FeedbackDeliveryResult,
    FeedbackNotConfirmedError,
    FeedbackOutcomeUnknownError,
    FeedbackPendingError,
    FeedbackSupersededError,
    FeedbackUnavailableError,
)
from custom_components.groupalarm_ha_connect.models import (
    DeadlineStatus,
    FeedbackEligibility,
    GroupAlarmCoordinatorData,
    OrganizationError,
    PersonalFeedback,
)


def _entry(
    organization_ids: list[int],
    *,
    durations: dict[str, int] | None = None,
    device_id: int | None = None,
) -> MockConfigEntry:
    options: dict[str, object] = {
        CONF_ORGANIZATION_DURATIONS: durations or {},
    }
    if device_id is not None:
        options[CONF_FEEDBACK_DEVICE_ID] = device_id
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_TOKEN: "token",
            CONF_USER_ID: 41,
            CONF_ORGANIZATION_IDS: organization_ids,
            CONF_ORGANIZATION_NAMES: {
                str(value): f"Org {value}" for value in organization_ids
            },
        },
        options=options,
        unique_id="test",
        version=3,
    )


def _list_alarm(
    alarm_id: int = 11,
    *,
    organization_id: int = 7,
    positive: int = 1,
) -> dict[str, object]:
    return {
        "id": alarm_id,
        "organizationID": organization_id,
        "startDate": f"2026-07-27T10:{alarm_id % 60:02d}:00Z",
        "event": {
            "id": organization_id * 10,
            "organizationID": organization_id,
            "archived": False,
        },
        "feedbackQuantity": {
            "positive": positive,
            "negative": 0,
            "unknown": 2,
        },
    }


def _page(
    alarm_id: int = 11,
    *,
    organization_id: int = 7,
    positive: int = 1,
) -> GroupAlarmAlarmPage:
    return GroupAlarmAlarmPage(
        alarms=(
            _list_alarm(
                alarm_id,
                organization_id=organization_id,
                positive=positive,
            ),
        ),
        total_alarms=1,
    )


def _detail(
    alarm_id: int = 11,
    *,
    organization_id: int = 7,
    response: bool | None = None,
    duration: int | None = None,
) -> dict[str, object]:
    feedback: list[dict[str, object]] = [
        {
            "alarmID": alarm_id,
            "userID": 41,
            "state": "WAITING",
            "feedback": False,
        }
    ]
    if response is not None:
        item: dict[str, object] = {
            "alarmID": alarm_id,
            "userID": 41,
            "state": "RESPONDED",
            "feedback": response,
        }
        if duration is not None:
            item["userDuration"] = duration
        feedback = [item]
    return {
        "id": alarm_id,
        "organizationID": organization_id,
        "message": f"Alarm {alarm_id}",
        "startDate": f"2026-07-27T10:{alarm_id % 60:02d}:00Z",
        "event": {
            "id": organization_id * 10,
            "name": f"E-{alarm_id}",
            "organizationID": organization_id,
            "archived": False,
        },
        "feedback": feedback,
        "feedbackQuantity": {
            "positive": 1,
            "negative": 0,
            "unknown": 2,
        },
    }


def _coordinator(
    hass: HomeAssistant,
    organization_ids: tuple[int, ...] = (7,),
    *,
    durations: dict[str, int] | None = None,
    device_id: int | None = None,
) -> tuple[GroupAlarmCoordinator, AsyncMock]:
    client = AsyncMock(spec=GroupAlarmClient)
    client.async_get_organization_timeout.return_value = 300
    coordinator = GroupAlarmCoordinator(
        hass,
        _entry(
            list(organization_ids),
            durations=durations,
            device_id=device_id,
        ),
        client,
        GroupAlarmUser(id=41),
        {value: f"Org {value}" for value in organization_ids},
        60,
    )
    return coordinator, client


async def _load_feedback_context(
    coordinator: GroupAlarmCoordinator,
    client: AsyncMock,
) -> None:
    """Load one alarm with a fixture-proven open local feedback window."""
    client.async_get_alarms.return_value = _page()
    client.async_get_alarm.return_value = _detail()
    coordinator.data = await coordinator._async_update_data()
    snapshot = coordinator.snapshot(7)
    assert snapshot.alarm is not None
    alarm = replace(snapshot.alarm, feedback_eligibility=FeedbackEligibility.OPEN)
    coordinator._alarms[7] = alarm
    coordinator.data = GroupAlarmCoordinatorData(
        organizations=(replace(snapshot, alarm=alarm),)
    )


async def test_stable_list_gate_reuses_detail(
    hass: HomeAssistant,
) -> None:
    coordinator, client = _coordinator(hass)
    client.async_get_alarms.return_value = _page()
    client.async_get_alarm.return_value = _detail()

    first = await coordinator._async_update_data()
    coordinator.data = first
    second = await coordinator._async_update_data()

    assert second == first
    assert client.async_get_alarms.await_count == 2
    client.async_get_alarms.assert_awaited_with(7, limit=10)
    client.async_get_alarm.assert_awaited_once_with(11)


async def test_new_alarm_loads_one_local_feedback_window(
    hass: HomeAssistant,
) -> None:
    """A new alarm loads its timeout once and reuses the resulting deadline."""
    coordinator, client = _coordinator(hass)
    client.async_get_alarms.return_value = _page()
    client.async_get_alarm.return_value = _detail()
    received_at = datetime(2026, 7, 29, 14, tzinfo=UTC)

    with (
        patch(
            "custom_components.groupalarm_ha_connect.coordinator._utcnow",
            side_effect=(
                received_at,
                received_at + timedelta(seconds=5),
                received_at + timedelta(seconds=5),
                received_at + timedelta(seconds=6),
            ),
        ),
        patch(
            "custom_components.groupalarm_ha_connect.coordinator."
            "async_track_time_interval",
            return_value=Mock(),
        ),
    ):
        first = await coordinator._async_update_data()
        coordinator.data = first
        second = await coordinator._async_update_data()

    alarm = second.for_organization(7).alarm
    assert alarm is not None
    assert alarm.feedback_deadline == received_at + timedelta(seconds=300)
    assert alarm.deadline_status is DeadlineStatus.KNOWN_ACTIVE
    assert alarm.feedback_eligibility is FeedbackEligibility.OPEN
    client.async_get_organization_timeout.assert_awaited_once_with(7)
    client.async_get_alarm.assert_awaited_once_with(11)


async def test_new_alarm_countdown_does_not_depend_on_button_eligibility(
    hass: HomeAssistant,
) -> None:
    """Every unclosed new alarm gets a countdown while unknown stays fail-safe."""
    coordinator, client = _coordinator(hass)
    client.async_get_alarms.return_value = _page()
    detail = _detail()
    detail["feedback"] = []
    client.async_get_alarm.return_value = detail
    received_at = datetime(2026, 7, 29, 14, tzinfo=UTC)

    with (
        patch(
            "custom_components.groupalarm_ha_connect.coordinator._utcnow",
            return_value=received_at,
        ),
        patch(
            "custom_components.groupalarm_ha_connect.coordinator."
            "async_track_time_interval",
            return_value=Mock(),
        ),
    ):
        coordinator.data = await coordinator._async_update_data()
        alarm = coordinator.snapshot(7).alarm
        assert alarm is not None
        assert alarm.deadline_status is DeadlineStatus.KNOWN_ACTIVE
        assert alarm.feedback_eligibility is FeedbackEligibility.UNKNOWN
        assert coordinator.feedback_countdown(7) == 300
        assert coordinator.can_send_feedback(7) is False


async def test_countdown_zero_closes_feedback_without_api_poll(
    hass: HomeAssistant,
) -> None:
    """The local zero boundary disables buttons and blocks every feedback POST."""
    coordinator, client = _coordinator(hass)
    client.async_get_alarms.return_value = _page()
    client.async_get_alarm.return_value = _detail()
    received_at = datetime(2026, 7, 29, 14, tzinfo=UTC)
    cancel = Mock()

    with (
        patch(
            "custom_components.groupalarm_ha_connect.coordinator._utcnow",
            return_value=received_at,
        ),
        patch(
            "custom_components.groupalarm_ha_connect.coordinator."
            "async_track_time_interval",
            return_value=cancel,
        ),
    ):
        coordinator.data = await coordinator._async_update_data()

    deadline = received_at + timedelta(seconds=300)
    with patch(
        "custom_components.groupalarm_ha_connect.coordinator._utcnow",
        return_value=deadline,
    ):
        assert coordinator.feedback_countdown(7) == 0
        assert coordinator.can_send_feedback(7) is False
        with pytest.raises(FeedbackUnavailableError):
            await coordinator.async_send_feedback(7, response=True)
        coordinator._async_countdown_tick(deadline)
        assert coordinator.feedback_countdown(7) == 0

    alarm = coordinator.snapshot(7).alarm
    assert alarm is not None
    assert alarm.deadline_status is DeadlineStatus.KNOWN_EXPIRED
    assert alarm.feedback_eligibility is FeedbackEligibility.CLOSED
    cancel.assert_called_once_with()
    assert client.async_get_alarms.await_count == 1
    assert client.async_get_alarm.await_count == 1
    assert client.async_get_organization_timeout.await_count == 1
    client.async_send_feedback.assert_not_awaited()
    client.async_send_feedback_with_duration.assert_not_awaited()


async def test_changed_fingerprint_refreshes_same_alarm_detail(
    hass: HomeAssistant,
) -> None:
    coordinator, client = _coordinator(hass)
    client.async_get_alarms.side_effect = (
        _page(positive=1),
        _page(positive=2),
    )
    client.async_get_alarm.return_value = _detail()

    coordinator.data = await coordinator._async_update_data()
    await coordinator._async_update_data()

    assert client.async_get_alarm.await_count == 2


async def test_new_alarm_id_replaces_canonical_state(
    hass: HomeAssistant,
) -> None:
    coordinator, client = _coordinator(hass)
    client.async_get_alarms.side_effect = (_page(11), _page(12))
    client.async_get_alarm.side_effect = (_detail(11), _detail(12))

    coordinator.data = await coordinator._async_update_data()
    updated = await coordinator._async_update_data()

    assert updated.for_organization(7).alarm is not None
    assert updated.for_organization(7).alarm.id == 12
    assert client.async_get_alarm.await_count == 2


async def test_safety_refresh_reloads_unchanged_detail(
    hass: HomeAssistant,
) -> None:
    coordinator, client = _coordinator(hass)
    client.async_get_alarms.return_value = _page()
    client.async_get_alarm.return_value = _detail()
    coordinator.data = await coordinator._async_update_data()
    coordinator._detail_loaded_at[7] = 0

    with patch(
        "custom_components.groupalarm_ha_connect.coordinator.monotonic",
        return_value=901,
    ):
        await coordinator._async_update_data()

    assert client.async_get_alarm.await_count == 2


async def test_no_alarm_clears_previous_alarm(
    hass: HomeAssistant,
) -> None:
    coordinator, client = _coordinator(hass)
    client.async_get_alarms.side_effect = (
        _page(),
        GroupAlarmAlarmPage(alarms=(), total_alarms=0),
    )
    client.async_get_alarm.return_value = _detail()

    coordinator.data = await coordinator._async_update_data()
    updated = await coordinator._async_update_data()

    snapshot = updated.for_organization(7)
    assert snapshot.available is True
    assert snapshot.alarm is None
    assert 7 not in coordinator._alarms


async def test_one_organization_failure_is_isolated(
    hass: HomeAssistant,
) -> None:
    coordinator, client = _coordinator(hass, (7, 12))

    async def get_alarms(
        organization_id: int,
        *,
        limit: int,
    ) -> GroupAlarmAlarmPage:
        assert limit == 10
        if organization_id == 12:
            raise GroupAlarmPermissionError(403)
        return _page(organization_id=organization_id)

    client.async_get_alarms.side_effect = get_alarms
    client.async_get_alarm.return_value = _detail(organization_id=7)

    data = await coordinator._async_update_data()

    assert data.for_organization(7).available is True
    failed = data.for_organization(12)
    assert failed.available is False
    assert failed.error is OrganizationError.PERMISSION


@pytest.mark.parametrize(
    "error",
    [
        GroupAlarmTransportError("offline"),
        GroupAlarmRateLimitError(120),
    ],
)
async def test_all_organizations_failure_raises_update_failed(
    hass: HomeAssistant,
    error: Exception,
) -> None:
    coordinator, client = _coordinator(hass, (7, 12))
    client.async_get_alarms.side_effect = error

    with pytest.raises(UpdateFailed) as raised:
        await coordinator._async_update_data()

    if isinstance(error, GroupAlarmRateLimitError):
        assert raised.value.retry_after == 120


async def test_authentication_failure_starts_reauth(
    hass: HomeAssistant,
) -> None:
    coordinator, client = _coordinator(hass)
    client.async_get_alarms.side_effect = GroupAlarmAuthenticationError(401)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_parallelism_is_bounded(
    hass: HomeAssistant,
) -> None:
    organization_ids = tuple(range(1, 9))
    coordinator, client = _coordinator(hass, organization_ids)
    active = 0
    maximum_active = 0
    release = asyncio.Event()

    async def get_alarms(
        organization_id: int,
        *,
        limit: int,
    ) -> GroupAlarmAlarmPage:
        nonlocal active, maximum_active
        assert limit == 10
        active += 1
        maximum_active = max(maximum_active, active)
        if maximum_active == MAX_PARALLEL_ORGANIZATIONS:
            release.set()
        await release.wait()
        await asyncio.sleep(0)
        active -= 1
        return GroupAlarmAlarmPage(alarms=(), total_alarms=0)

    client.async_get_alarms.side_effect = get_alarms

    await coordinator._async_update_data()

    assert maximum_active == MAX_PARALLEL_ORGANIZATIONS


async def test_standard_feedback_changes_state_only_after_detail_confirmation(
    hass: HomeAssistant,
) -> None:
    coordinator, client = _coordinator(
        hass,
        durations={"7": 12},
        device_id=91,
    )
    await _load_feedback_context(coordinator, client)

    async def send_feedback(**kwargs: object) -> None:
        assert kwargs == {
            "alarm_id": 11,
            "organization_id": 7,
            "user_id": 41,
            "response": False,
        }
        assert coordinator.snapshot(7).personal_feedback is PersonalFeedback.UNKNOWN

    client.async_send_feedback.side_effect = send_feedback
    client.async_get_alarm.return_value = _detail(response=False)

    result = await coordinator.async_send_feedback(7, response=False)

    assert result is FeedbackDeliveryResult.CONFIRMED
    assert coordinator.snapshot(7).personal_feedback is PersonalFeedback.NEGATIVE
    assert coordinator.snapshot(7).deadline_status is DeadlineStatus.ANSWERED
    assert coordinator.feedback_countdown(7) is None
    assert coordinator._unsub_countdown is None
    client.async_send_feedback_with_duration.assert_not_awaited()


async def test_positive_feedback_without_duration_uses_messaging_endpoint(
    hass: HomeAssistant,
) -> None:
    coordinator, client = _coordinator(hass)
    await _load_feedback_context(coordinator, client)
    client.async_get_alarm.return_value = _detail(response=True)

    result = await coordinator.async_send_feedback(7, response=True)

    assert result is FeedbackDeliveryResult.CONFIRMED
    client.async_send_feedback.assert_awaited_once_with(
        alarm_id=11,
        organization_id=7,
        user_id=41,
        response=True,
    )
    client.async_send_feedback_with_duration.assert_not_awaited()


async def test_positive_feedback_with_duration_uses_only_app_endpoint(
    hass: HomeAssistant,
) -> None:
    coordinator, client = _coordinator(
        hass,
        durations={"7": 12},
        device_id=91,
    )
    await _load_feedback_context(coordinator, client)
    client.async_get_alarm.return_value = _detail(response=True, duration=12)

    result = await coordinator.async_send_feedback(7, response=True)

    assert result is FeedbackDeliveryResult.CONFIRMED
    client.async_send_feedback_with_duration.assert_awaited_once_with(
        alarm_id=11,
        device_id=91,
        duration=12,
    )
    client.async_send_feedback.assert_not_awaited()
    assert coordinator.snapshot(7).alarm is not None
    assert coordinator.snapshot(7).alarm.personal_feedback_duration == 12


async def test_explicit_duration_rejection_uses_confirmed_standard_fallback(
    hass: HomeAssistant,
) -> None:
    coordinator, client = _coordinator(
        hass,
        durations={"7": 12},
        device_id=91,
    )
    await _load_feedback_context(coordinator, client)
    client.async_send_feedback_with_duration.side_effect = GroupAlarmRequestError(400)
    client.async_get_alarm.return_value = _detail(response=True)

    result = await coordinator.async_send_feedback(7, response=True)

    assert result is FeedbackDeliveryResult.CONFIRMED_WITHOUT_DURATION
    client.async_send_feedback.assert_awaited_once_with(
        alarm_id=11,
        organization_id=7,
        user_id=41,
        response=True,
    )


async def test_duration_fallback_is_blocked_when_countdown_reaches_zero(
    hass: HomeAssistant,
) -> None:
    """A delayed app rejection cannot start a fallback POST after expiry."""
    coordinator, client = _coordinator(
        hass,
        durations={"7": 12},
        device_id=91,
    )
    await _load_feedback_context(coordinator, client)
    alarm = coordinator.snapshot(7).alarm
    assert alarm is not None
    assert alarm.feedback_deadline is not None
    client.async_send_feedback_with_duration.side_effect = GroupAlarmRequestError(400)
    before_deadline = alarm.feedback_deadline - timedelta(seconds=1)

    with (
        patch(
            "custom_components.groupalarm_ha_connect.coordinator._utcnow",
            side_effect=(
                before_deadline,
                before_deadline,
                before_deadline,
                alarm.feedback_deadline,
            ),
        ),
        pytest.raises(FeedbackUnavailableError),
    ):
        await coordinator.async_send_feedback(7, response=True)

    client.async_send_feedback_with_duration.assert_awaited_once()
    client.async_send_feedback.assert_not_awaited()


async def test_unknown_app_write_is_reconciled_without_blind_fallback(
    hass: HomeAssistant,
) -> None:
    coordinator, client = _coordinator(
        hass,
        durations={"7": 12},
        device_id=91,
    )
    await _load_feedback_context(coordinator, client)
    client.async_send_feedback_with_duration.side_effect = GroupAlarmTransportError(
        "offline"
    )
    client.async_get_alarm.return_value = _detail(response=True, duration=12)

    result = await coordinator.async_send_feedback(7, response=True)

    assert result is FeedbackDeliveryResult.CONFIRMED
    client.async_send_feedback.assert_not_awaited()


async def test_confirmed_feedback_with_unverified_duration_does_not_fallback(
    hass: HomeAssistant,
) -> None:
    coordinator, client = _coordinator(
        hass,
        durations={"7": 12},
        device_id=91,
    )
    await _load_feedback_context(coordinator, client)
    client.async_get_alarm.return_value = _detail(response=True)

    with patch(
        "custom_components.groupalarm_ha_connect.coordinator."
        "FEEDBACK_RECONCILIATION_DELAYS",
        (0.0, 0.0, 0.0),
    ):
        result = await coordinator.async_send_feedback(7, response=True)

    assert result is FeedbackDeliveryResult.CONFIRMED_DURATION_UNVERIFIED
    assert client.async_get_alarm.await_count == 4
    client.async_send_feedback.assert_not_awaited()


async def test_unknown_app_write_without_confirmation_never_falls_back(
    hass: HomeAssistant,
) -> None:
    coordinator, client = _coordinator(
        hass,
        durations={"7": 12},
        device_id=91,
    )
    await _load_feedback_context(coordinator, client)
    client.async_send_feedback_with_duration.side_effect = GroupAlarmTransportError(
        "offline"
    )
    client.async_get_alarm.return_value = _detail()

    with (
        patch(
            "custom_components.groupalarm_ha_connect.coordinator."
            "FEEDBACK_RECONCILIATION_DELAYS",
            (0.0, 0.0, 0.0),
        ),
        pytest.raises(FeedbackOutcomeUnknownError),
    ):
        await coordinator.async_send_feedback(7, response=True)

    client.async_send_feedback.assert_not_awaited()
    assert coordinator._pending_feedback == {(7, 11): True}
    assert coordinator.can_send_feedback(7) is False
    assert coordinator.snapshot(7).personal_feedback is PersonalFeedback.UNKNOWN


async def test_pending_feedback_forces_detail_on_next_regular_poll(
    hass: HomeAssistant,
) -> None:
    coordinator, client = _coordinator(hass)
    await _load_feedback_context(coordinator, client)
    client.async_send_feedback.side_effect = GroupAlarmTransportError("offline")
    client.async_get_alarm.return_value = _detail()
    with (
        patch(
            "custom_components.groupalarm_ha_connect.coordinator."
            "FEEDBACK_RECONCILIATION_DELAYS",
            (0.0, 0.0, 0.0),
        ),
        pytest.raises(FeedbackOutcomeUnknownError),
    ):
        await coordinator.async_send_feedback(7, response=False)

    client.async_get_alarm.reset_mock()
    client.async_get_alarm.return_value = _detail(response=False)
    updated = await coordinator._async_update_data()

    assert client.async_get_alarm.await_count == 1
    assert updated.for_organization(7).personal_feedback is PersonalFeedback.NEGATIVE
    assert coordinator._pending_feedback == {}


async def test_parallel_double_press_is_rejected_instead_of_queued(
    hass: HomeAssistant,
) -> None:
    coordinator, client = _coordinator(hass)
    await _load_feedback_context(coordinator, client)
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked_send(**_kwargs: object) -> None:
        started.set()
        await release.wait()

    client.async_send_feedback.side_effect = blocked_send
    client.async_get_alarm.return_value = _detail(response=True)

    first = asyncio.create_task(coordinator.async_send_feedback(7, response=True))
    await started.wait()
    with pytest.raises(FeedbackBusyError):
        await coordinator.async_send_feedback(7, response=True)
    release.set()

    assert await first is FeedbackDeliveryResult.CONFIRMED
    assert client.async_send_feedback.await_count == 1


async def test_new_alarm_during_reconciliation_never_overwrites_new_state(
    hass: HomeAssistant,
) -> None:
    coordinator, client = _coordinator(hass)
    await _load_feedback_context(coordinator, client)

    async def replace_reference(_alarm_id: int) -> dict[str, object]:
        coordinator._references[7] = replace(coordinator._references[7], id=12)
        return _detail(response=True)

    client.async_get_alarm.side_effect = replace_reference

    with pytest.raises(FeedbackSupersededError):
        await coordinator.async_send_feedback(7, response=True)

    assert coordinator._references[7].id == 12
    assert coordinator._alarms[7].id == 11
    assert coordinator.snapshot(7).personal_feedback is PersonalFeedback.UNKNOWN


async def test_button_uses_translated_safe_action_errors(
    hass: HomeAssistant,
) -> None:
    coordinator, client = _coordinator(hass)
    await _load_feedback_context(coordinator, client)
    button = GroupAlarmFeedbackButton(coordinator, 7, BUTTONS[0][0], True)
    button.hass = hass

    assert button.available is True
    with (
        patch.object(
            coordinator,
            "async_send_feedback",
            new=AsyncMock(side_effect=FeedbackOutcomeUnknownError),
        ),
        pytest.raises(ServiceValidationError) as raised,
    ):
        await button.async_press()

    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == "feedback_outcome_unknown"


async def test_button_notifies_about_confirmed_duration_fallback(
    hass: HomeAssistant,
) -> None:
    coordinator, client = _coordinator(hass)
    await _load_feedback_context(coordinator, client)
    button = GroupAlarmFeedbackButton(coordinator, 7, BUTTONS[0][0], True)
    button.hass = hass
    translation_key = (
        f"component.{DOMAIN}.exceptions.feedback_sent_without_duration.message"
    )

    with (
        patch.object(
            coordinator,
            "async_send_feedback",
            new=AsyncMock(
                return_value=FeedbackDeliveryResult.CONFIRMED_WITHOUT_DURATION
            ),
        ),
        patch(
            "custom_components.groupalarm_ha_connect.button.async_get_translations",
            new=AsyncMock(
                return_value={
                    translation_key: (
                        "Rückmeldung wurde gesendet, die Anfahrtszeit konnte "
                        "jedoch nicht übertragen werden."
                    )
                }
            ),
        ),
        patch(
            "custom_components.groupalarm_ha_connect.button.async_create"
        ) as create_notification,
    ):
        await button.async_press()

    create_notification.assert_called_once_with(
        hass,
        (
            "Rückmeldung wurde gesendet, die Anfahrtszeit konnte jedoch "
            "nicht übertragen werden."
        ),
        title="GroupAlarm HA Connect",
        notification_id=f"{DOMAIN}_feedback_7",
    )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (GroupAlarmPermissionError(403), OrganizationError.PERMISSION),
        (GroupAlarmRateLimitError(30), OrganizationError.RATE_LIMIT),
        (GroupAlarmRequestError(400), OrganizationError.REQUEST),
        (
            GroupAlarmResponseError("invalid"),
            OrganizationError.RESPONSE,
        ),
        (GroupAlarmServerError(500), OrganizationError.SERVER),
        (GroupAlarmTransportError("offline"), OrganizationError.TRANSPORT),
    ],
)
def test_api_errors_are_classified_without_payloads(
    error: GroupAlarmError,
    expected: OrganizationError,
) -> None:
    """Every isolatable API error maps to one stable diagnostic value."""
    assert _classify_error(error) is expected
    with pytest.raises(TypeError, match="Unsupported"):
        _classify_error(GroupAlarmError("unsupported"))


def test_pending_and_feedback_configuration_boundaries(
    hass: HomeAssistant,
) -> None:
    """Pending writes and malformed options fail before any POST."""
    coordinator, _client = _coordinator(hass)
    coordinator._pending_feedback = {(7, 10): True, (7, 11): False, (12, 1): True}
    coordinator._clear_pending_feedback(7, keep_alarm_id=11)
    assert coordinator._pending_feedback == {(7, 11): False, (12, 1): True}

    invalid_durations, _ = _coordinator(
        hass,
        durations="invalid",  # type: ignore[arg-type]
    )
    with pytest.raises(FeedbackConfigurationError):
        invalid_durations._arrival_duration(7)

    invalid_duration, _ = _coordinator(
        hass,
        durations={"7": 181},
    )
    with pytest.raises(FeedbackConfigurationError):
        invalid_duration._arrival_duration(7)

    for device_id in (False, 0):
        invalid_device, _ = _coordinator(
            hass,
            durations={"7": 12},
            device_id=device_id,
        )
        with pytest.raises(FeedbackConfigurationError):
            invalid_device._feedback_device_id()


async def test_feedback_validation_handles_missing_and_pending_state(
    hass: HomeAssistant,
) -> None:
    """Absent coordinator state and unresolved writes stay unavailable."""
    coordinator, client = _coordinator(hass)
    with pytest.raises(FeedbackUnavailableError):
        coordinator._validated_feedback_alarm(7)

    await _load_feedback_context(coordinator, client)
    coordinator._pending_feedback[(7, 11)] = True
    with pytest.raises(FeedbackPendingError):
        coordinator._validated_feedback_alarm(7)


async def test_reconciliation_detects_superseded_target_around_delay(
    hass: HomeAssistant,
) -> None:
    """A replacement alarm cancels reconciliation before or after sleeping."""
    coordinator, client = _coordinator(hass)
    await _load_feedback_context(coordinator, client)

    with (
        patch.object(coordinator, "_target_is_current", return_value=False),
        pytest.raises(FeedbackSupersededError),
    ):
        await coordinator._async_reconcile_feedback(
            organization_id=7,
            alarm_id=11,
            response=True,
            duration=None,
        )

    with (
        patch(
            "custom_components.groupalarm_ha_connect.coordinator."
            "FEEDBACK_RECONCILIATION_DELAYS",
            (1.0,),
        ),
        patch(
            "custom_components.groupalarm_ha_connect.coordinator.asyncio.sleep",
            new=AsyncMock(),
        ),
        patch.object(
            coordinator,
            "_target_is_current",
            side_effect=(True, False),
        ),
        pytest.raises(FeedbackSupersededError),
    ):
        await coordinator._async_reconcile_feedback(
            organization_id=7,
            alarm_id=11,
            response=True,
            duration=None,
        )


@pytest.mark.parametrize(
    "error",
    [
        GroupAlarmAuthenticationError(401),
        GroupAlarmTransportError("offline"),
    ],
)
async def test_reconciliation_api_failure_boundaries(
    hass: HomeAssistant,
    error: GroupAlarmError,
) -> None:
    """Authentication escapes immediately; transient GET errors exhaust retries."""
    coordinator, client = _coordinator(hass)
    await _load_feedback_context(coordinator, client)
    client.async_get_alarm.side_effect = error

    with patch(
        "custom_components.groupalarm_ha_connect.coordinator."
        "FEEDBACK_RECONCILIATION_DELAYS",
        (0.0,),
    ):
        if isinstance(error, GroupAlarmAuthenticationError):
            with pytest.raises(GroupAlarmAuthenticationError):
                await coordinator._async_reconcile_feedback(
                    organization_id=7,
                    alarm_id=11,
                    response=True,
                    duration=None,
                )
        else:
            assert (
                await coordinator._async_reconcile_feedback(
                    organization_id=7,
                    alarm_id=11,
                    response=True,
                    duration=None,
                )
                is None
            )


async def test_reconciliation_rejects_opposite_server_confirmation(
    hass: HomeAssistant,
) -> None:
    """A server-confirmed opposite answer is an explicit conflict."""
    coordinator, client = _coordinator(hass)
    await _load_feedback_context(coordinator, client)
    client.async_get_alarm.return_value = _detail(response=False)
    with pytest.raises(FeedbackConflictError):
        await coordinator._async_reconcile_feedback(
            organization_id=7,
            alarm_id=11,
            response=True,
            duration=None,
        )
    assert coordinator._pending_feedback == {}


async def test_standard_transport_failure_can_still_reconcile(
    hass: HomeAssistant,
) -> None:
    """An uncertain messaging POST is accepted only after canonical confirmation."""
    coordinator, client = _coordinator(hass)
    await _load_feedback_context(coordinator, client)
    client.async_send_feedback.side_effect = GroupAlarmTransportError("offline")
    client.async_get_alarm.return_value = _detail(response=True)
    assert (
        await coordinator.async_send_feedback(7, response=True)
        is FeedbackDeliveryResult.CONFIRMED
    )


async def test_successful_posts_without_confirmation_fail_closed(
    hass: HomeAssistant,
) -> None:
    """A successful HTTP response alone never becomes confirmed feedback."""
    standard, standard_client = _coordinator(hass)
    await _load_feedback_context(standard, standard_client)
    standard_client.async_get_alarm.return_value = _detail()
    with (
        patch(
            "custom_components.groupalarm_ha_connect.coordinator."
            "FEEDBACK_RECONCILIATION_DELAYS",
            (0.0,),
        ),
        pytest.raises(FeedbackNotConfirmedError),
    ):
        await standard.async_send_feedback(7, response=False)

    timed, timed_client = _coordinator(
        hass,
        durations={"7": 12},
        device_id=91,
    )
    await _load_feedback_context(timed, timed_client)
    timed_client.async_get_alarm.return_value = _detail()
    with (
        patch(
            "custom_components.groupalarm_ha_connect.coordinator."
            "FEEDBACK_RECONCILIATION_DELAYS",
            (0.0,),
        ),
        pytest.raises(FeedbackNotConfirmedError),
    ):
        await timed.async_send_feedback(7, response=True)


async def test_feedback_target_changed_before_delivery(
    hass: HomeAssistant,
) -> None:
    """A target replacement between lock acquisition and POST aborts delivery."""
    coordinator, client = _coordinator(hass)
    await _load_feedback_context(coordinator, client)
    alarm = coordinator.snapshot(7).alarm
    assert alarm is not None
    with (
        patch.object(
            coordinator,
            "_validated_feedback_alarm",
            side_effect=(alarm, replace(alarm, id=12)),
        ),
        pytest.raises(FeedbackSupersededError),
    ):
        await coordinator.async_send_feedback(7, response=True)
    client.async_send_feedback.assert_not_awaited()


async def test_previous_alarm_falls_back_to_coordinator_cache(
    hass: HomeAssistant,
) -> None:
    """A partial previous data set can still retain cached state for another org."""
    coordinator, client = _coordinator(hass, (7, 12))
    await _load_feedback_context(coordinator, client)
    cached = coordinator._alarms[7]
    coordinator.data = GroupAlarmCoordinatorData(
        organizations=(
            replace(
                coordinator.snapshot(7),
                organization_id=12,
                organization_name="Org 12",
            ),
        )
    )
    assert coordinator._previous_alarm(7) is cached


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (FeedbackUnavailableError(), "feedback_unavailable"),
        (FeedbackBusyError(), "feedback_busy"),
        (FeedbackPendingError(), "feedback_pending"),
        (FeedbackConfigurationError(), "feedback_configuration"),
        (FeedbackNotConfirmedError(), "feedback_not_confirmed"),
        (FeedbackOutcomeUnknownError(), "feedback_outcome_unknown"),
        (FeedbackSupersededError(), "feedback_superseded"),
        (FeedbackConflictError(), "feedback_conflict"),
        (FeedbackActionError(), "feedback_failed"),
    ],
)
def test_feedback_action_translation_keys(
    error: FeedbackActionError,
    key: str,
) -> None:
    """Every sanitized domain action has a stable translation key."""
    assert _action_exception_key(error) == key


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (GroupAlarmAuthenticationError(401), "feedback_authentication"),
        (GroupAlarmPermissionError(403), "feedback_permission"),
        (GroupAlarmRateLimitError(30), "feedback_rate_limited"),
        (GroupAlarmRequestError(400), "feedback_rejected"),
        (FeedbackUnavailableError(), "feedback_unavailable"),
        (GroupAlarmResponseError("invalid"), "feedback_failed"),
    ],
)
async def test_button_maps_all_safe_service_errors(
    hass: HomeAssistant,
    error: GroupAlarmError | FeedbackActionError,
    key: str,
) -> None:
    """Button failures expose translations without raw exception content."""
    coordinator, client = _coordinator(hass)
    await _load_feedback_context(coordinator, client)
    button = GroupAlarmFeedbackButton(coordinator, 7, BUTTONS[0][0], True)
    button.hass = hass
    with (
        patch.object(
            coordinator,
            "async_send_feedback",
            new=AsyncMock(side_effect=error),
        ),
        patch.object(coordinator.entry, "async_start_reauth") as start_reauth,
        pytest.raises(ServiceValidationError) as raised,
    ):
        await button.async_press()
    assert raised.value.translation_key == key
    assert start_reauth.call_count == int(
        isinstance(error, GroupAlarmAuthenticationError)
    )


async def test_button_notification_noop_and_fallback_message(
    hass: HomeAssistant,
) -> None:
    """Normal confirmation is silent; missing translations use safe built-ins."""
    coordinator, client = _coordinator(hass)
    await _load_feedback_context(coordinator, client)
    button = GroupAlarmFeedbackButton(coordinator, 7, BUTTONS[0][0], True)
    button.hass = hass

    with patch(
        "custom_components.groupalarm_ha_connect.button.async_create"
    ) as create_notification:
        await button._async_notify_degraded_result(FeedbackDeliveryResult.CONFIRMED)
    create_notification.assert_not_called()

    with (
        patch(
            "custom_components.groupalarm_ha_connect.button.async_get_translations",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "custom_components.groupalarm_ha_connect.button.async_create"
        ) as create_notification,
    ):
        await button._async_notify_degraded_result(
            FeedbackDeliveryResult.CONFIRMED_DURATION_UNVERIFIED
        )
    assert "could not be verified" in create_notification.call_args.args[1]
