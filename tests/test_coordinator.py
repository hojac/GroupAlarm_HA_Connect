"""Tests for low-traffic coordinated polling and error isolation."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, patch

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
    GroupAlarmPermissionError,
    GroupAlarmRateLimitError,
    GroupAlarmRequestError,
    GroupAlarmTransportError,
    GroupAlarmUser,
)
from custom_components.groupalarm_ha_connect.button import (
    BUTTONS,
    GroupAlarmFeedbackButton,
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
)
from custom_components.groupalarm_ha_connect.feedback import (
    FeedbackBusyError,
    FeedbackDeliveryResult,
    FeedbackOutcomeUnknownError,
    FeedbackSupersededError,
)
from custom_components.groupalarm_ha_connect.models import (
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
    feedback: list[dict[str, object]] = []
    if response is not None:
        item: dict[str, object] = {
            "alarmID": alarm_id,
            "userID": 41,
            "state": "RESPONDED",
            "feedback": response,
        }
        if duration is not None:
            item["userDuration"] = duration
        feedback.append(item)
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
    """Load one alarm and mark only its eligibility as fixture-proven open."""
    client.async_get_alarms.return_value = _page()
    client.async_get_alarm.return_value = _detail()
    coordinator.data = await coordinator._async_update_data()
    snapshot = coordinator.snapshot(7)
    assert snapshot.alarm is not None
    alarm = replace(
        snapshot.alarm,
        feedback_eligibility=FeedbackEligibility.OPEN,
    )
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
