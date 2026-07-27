"""Home Assistant lifecycle, device, and entity tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_TOKEN, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.groupalarm_ha_connect import _migrate_registries
from custom_components.groupalarm_ha_connect.api import (
    GroupAlarmAlarmPage,
    GroupAlarmClient,
    GroupAlarmOrganization,
    GroupAlarmPermissionError,
    GroupAlarmUser,
)
from custom_components.groupalarm_ha_connect.const import (
    CONF_ORGANIZATION_DURATIONS,
    CONF_ORGANIZATION_IDS,
    CONF_ORGANIZATION_NAMES,
    CONF_SCAN_INTERVAL,
    CONF_USER_ID,
    DOMAIN,
)
from custom_components.groupalarm_ha_connect.models import (
    build_device_identifier,
    build_entity_unique_id,
)


def _entry(organization_ids: tuple[int, ...] = (7, 12)) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="GroupAlarm HA Connect",
        data={
            CONF_TOKEN: "token",
            CONF_USER_ID: 41,
            CONF_ORGANIZATION_IDS: list(organization_ids),
            CONF_ORGANIZATION_NAMES: {
                str(value): f"Org {value}" for value in organization_ids
            },
        },
        options={
            CONF_SCAN_INTERVAL: 60,
            CONF_ORGANIZATION_DURATIONS: {},
        },
        unique_id=(
            "user_41_organizations_"
            + "-".join(str(value) for value in organization_ids)
        ),
        version=3,
    )


def _page(organization_id: int) -> GroupAlarmAlarmPage:
    alarm_id = organization_id + 100
    return GroupAlarmAlarmPage(
        alarms=(
            {
                "id": alarm_id,
                "organizationID": organization_id,
                "startDate": "2026-07-27T10:00:00Z",
                "event": {
                    "id": organization_id * 10,
                    "organizationID": organization_id,
                    "archived": False,
                },
                "feedbackQuantity": {
                    "positive": 2,
                    "negative": 1,
                    "unknown": 3,
                },
            },
        ),
        total_alarms=1,
    )


def _detail(organization_id: int) -> dict[str, object]:
    alarm_id = organization_id + 100
    return {
        "id": alarm_id,
        "organizationID": organization_id,
        "message": f"Alarm for {organization_id}",
        "startDate": "2026-07-27T10:00:00Z",
        "event": {
            "id": organization_id * 10,
            "name": f"E-{organization_id}",
            "organizationID": organization_id,
            "archived": False,
        },
        "feedback": [],
        "feedbackQuantity": {
            "positive": 2,
            "negative": 1,
            "unknown": 3,
        },
    }


def _api_patches(
    *,
    failing_organizations: set[int] | None = None,
) -> tuple[object, ...]:
    failures = failing_organizations if failing_organizations is not None else set()

    async def get_alarms(
        _client: GroupAlarmClient,
        organization_id: int,
        *,
        limit: int = 10,
        offset: int = 0,
    ) -> GroupAlarmAlarmPage:
        assert limit == 10
        assert offset == 0
        if organization_id in failures:
            raise GroupAlarmPermissionError(403)
        return _page(organization_id)

    async def get_alarm(
        _client: GroupAlarmClient,
        alarm_id: int,
    ) -> dict[str, object]:
        return _detail(alarm_id - 100)

    return (
        patch.object(
            GroupAlarmClient,
            "async_get_current_user",
            new=AsyncMock(return_value=GroupAlarmUser(id=41)),
        ),
        patch.object(
            GroupAlarmClient,
            "async_get_organizations",
            new=AsyncMock(
                return_value=(
                    GroupAlarmOrganization(id=7, name="Alpha"),
                    GroupAlarmOrganization(id=12, name="Bravo"),
                )
            ),
        ),
        patch.object(
            GroupAlarmClient,
            "async_get_alarms",
            new=get_alarms,
        ),
        patch.object(
            GroupAlarmClient,
            "async_get_alarm",
            new=get_alarm,
        ),
    )


async def test_setup_creates_stable_devices_and_read_entities(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    patches = _api_patches()
    with patches[0], patches[1], patches[2], patches[3]:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    entries = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    assert len(entries) == 24

    for organization_id, expected_name in ((7, "Alpha"), (12, "Bravo")):
        device = device_registry.async_get_device(
            identifiers={
                (
                    DOMAIN,
                    build_device_identifier(41, organization_id),
                )
            }
        )
        assert device is not None
        assert device.name == f"GroupAlarm HA Connect {expected_name}"
        assert device.manufacturer == "GroupAlarm"
        assert device.entry_type is dr.DeviceEntryType.SERVICE

        alarm_entity_id = entity_registry.async_get_entity_id(
            "sensor",
            DOMAIN,
            build_entity_unique_id(41, organization_id, "alarm_id"),
        )
        assert alarm_entity_id is not None
        assert hass.states.get(alarm_entity_id).state == str(organization_id + 100)

        feedback_entity_id = entity_registry.async_get_entity_id(
            "sensor",
            DOMAIN,
            build_entity_unique_id(41, organization_id, "my_feedback"),
        )
        assert feedback_entity_id is not None
        assert hass.states.get(feedback_entity_id).state == "unknown"

        activity_entity_id = entity_registry.async_get_entity_id(
            "binary_sensor",
            DOMAIN,
            build_entity_unique_id(41, organization_id, "active_alert"),
        )
        assert activity_entity_id is not None
        assert hass.states.get(activity_entity_id).state == STATE_UNKNOWN

        tracker_entity_id = entity_registry.async_get_entity_id(
            "device_tracker",
            DOMAIN,
            build_entity_unique_id(41, organization_id, "location_tracker"),
        )
        assert tracker_entity_id is not None
        assert hass.states.get(tracker_entity_id).state == STATE_UNAVAILABLE


async def test_partial_failure_and_recovery_affect_only_one_organization(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    failures = {12}
    patches = _api_patches(failing_organizations=failures)
    with patches[0], patches[1], patches[2], patches[3]:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity_registry = er.async_get(hass)
        healthy_id = entity_registry.async_get_entity_id(
            "sensor",
            DOMAIN,
            build_entity_unique_id(41, 7, "alarm_id"),
        )
        failing_id = entity_registry.async_get_entity_id(
            "sensor",
            DOMAIN,
            build_entity_unique_id(41, 12, "alarm_id"),
        )
        assert healthy_id is not None
        assert failing_id is not None
        assert hass.states.get(healthy_id).state == "107"
        assert hass.states.get(failing_id).state == STATE_UNAVAILABLE

        failures.clear()
        await entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()

    assert hass.states.get(failing_id).state == "112"


async def test_unload_removes_states_and_stops_coordinator(
    hass: HomeAssistant,
) -> None:
    entry = _entry((7,))
    entry.add_to_hass(hass)
    patches = _api_patches()
    with patches[0], patches[1], patches[2], patches[3]:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    alarm_entity_id = entity_registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        build_entity_unique_id(41, 7, "alarm_id"),
    )
    assert alarm_entity_id is not None
    assert hass.states.get(alarm_entity_id) is not None
    coordinator = entry.runtime_data.coordinator

    with patch.object(
        coordinator,
        "async_shutdown",
        wraps=coordinator.async_shutdown,
    ) as shutdown:
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert shutdown.await_count == 1
    assert hass.states.get(alarm_entity_id).state == STATE_UNAVAILABLE
    assert not coordinator._listeners
    assert coordinator._unsub_refresh is None


async def test_registry_migration_preserves_selected_and_removes_stale(
    hass: HomeAssistant,
) -> None:
    entry = _entry((7,))
    entry.add_to_hass(hass)
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    selected_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "7")},
        name="Legacy selected",
    )
    stale_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "12")},
        name="Legacy stale",
    )
    selected_entity = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_7_alarm_id",
        config_entry=entry,
        device_id=selected_device.id,
        suggested_object_id="legacy_selected",
    )
    stale_entity = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_12_alarm_id",
        config_entry=entry,
        device_id=stale_device.id,
        suggested_object_id="legacy_stale",
    )

    _migrate_registries(
        hass,
        entry,
        user_id=41,
        organization_ids={7},
    )

    migrated = entity_registry.async_get(selected_entity.entity_id)
    assert migrated is not None
    assert migrated.unique_id == build_entity_unique_id(41, 7, "alarm_id")
    assert entity_registry.async_get(stale_entity.entity_id) is None

    selected_after = device_registry.async_get(selected_device.id)
    assert selected_after is not None
    assert selected_after.identifiers == {(DOMAIN, build_device_identifier(41, 7))}
    stale_after = device_registry.async_get(stale_device.id)
    assert stale_after is None or entry.entry_id not in stale_after.config_entries
