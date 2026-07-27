"""Tests for low-traffic coordinated polling and error isolation."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.groupalarm_ha_connect.api import (
    GroupAlarmAlarmPage,
    GroupAlarmAuthenticationError,
    GroupAlarmClient,
    GroupAlarmPermissionError,
    GroupAlarmRateLimitError,
    GroupAlarmTransportError,
    GroupAlarmUser,
)
from custom_components.groupalarm_ha_connect.const import (
    CONF_ORGANIZATION_IDS,
    CONF_ORGANIZATION_NAMES,
    CONF_USER_ID,
    DOMAIN,
    MAX_PARALLEL_ORGANIZATIONS,
)
from custom_components.groupalarm_ha_connect.coordinator import (
    GroupAlarmCoordinator,
)
from custom_components.groupalarm_ha_connect.models import OrganizationError


def _entry(organization_ids: list[int]) -> MockConfigEntry:
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
) -> dict[str, object]:
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
        "feedback": [],
        "feedbackQuantity": {
            "positive": 1,
            "negative": 0,
            "unknown": 2,
        },
    }


def _coordinator(
    hass: HomeAssistant,
    organization_ids: tuple[int, ...] = (7,),
) -> tuple[GroupAlarmCoordinator, AsyncMock]:
    client = AsyncMock(spec=GroupAlarmClient)
    coordinator = GroupAlarmCoordinator(
        hass,
        _entry(list(organization_ids)),
        client,
        GroupAlarmUser(id=41),
        {value: f"Org {value}" for value in organization_ids},
        60,
    )
    return coordinator, client


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
