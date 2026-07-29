"""Tests for privacy-preserving diagnostics."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.groupalarm_ha_connect.api import (
    GroupAlarmClient,
    GroupAlarmUser,
)
from custom_components.groupalarm_ha_connect.const import (
    CONF_FEEDBACK_DEVICE_ID,
    CONF_ORGANIZATION_DURATIONS,
    CONF_ORGANIZATION_IDS,
    CONF_ORGANIZATION_NAMES,
    CONF_SCAN_INTERVAL,
    CONF_USER_ID,
    DOMAIN,
)
from custom_components.groupalarm_ha_connect.coordinator import GroupAlarmCoordinator
from custom_components.groupalarm_ha_connect.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.groupalarm_ha_connect.models import (
    AlarmActivity,
    AlarmLocation,
    DeadlineStatus,
    FeedbackCounts,
    FeedbackEligibility,
    GroupAlarmAlarm,
    GroupAlarmCoordinatorData,
    GroupAlarmRuntimeData,
    OrganizationError,
    OrganizationSnapshot,
    PersonalFeedback,
)


def _alarm() -> GroupAlarmAlarm:
    """Return a snapshot containing values diagnostics must never expose."""
    return GroupAlarmAlarm(
        id=876_543_210,
        organization_id=987_654_321,
        message="Sensitive alarm text for Alice",
        started_at=datetime(2026, 7, 27, 12, tzinfo=UTC),
        closed_at=None,
        event_id=765_432_109,
        event_name="Sensitive event name",
        event_closed_at=None,
        event_archived=False,
        event_abort_present=False,
        feedback_counts=FeedbackCounts(positive=3, negative=1, unknown=2),
        personal_feedback=PersonalFeedback.UNKNOWN,
        personal_feedback_duration=None,
        activity=AlarmActivity.UNKNOWN,
        feedback_eligibility=FeedbackEligibility.UNKNOWN,
        feedback_deadline=None,
        deadline_status=DeadlineStatus.UNKNOWN,
        location=AlarmLocation(
            address="Sensitive Street 1",
            latitude=50.123456,
            longitude=6.654321,
        ),
    )


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create a config entry with deliberately sensitive values."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Sensitive Organization",
        data={
            CONF_TOKEN: "real-looking-groupalarm-secret",
            CONF_USER_ID: 654_321_987,
            CONF_ORGANIZATION_IDS: [987_654_321, 123_456_789],
            CONF_ORGANIZATION_NAMES: {
                "987654321": "Sensitive Organization",
                "123456789": "Other Sensitive Organization",
            },
        },
        options={
            CONF_SCAN_INTERVAL: 60,
            CONF_ORGANIZATION_DURATIONS: {"987654321": 12},
            CONF_FEEDBACK_DEVICE_ID: 543_219_876,
        },
        unique_id="sensitive-unique-id",
        version=3,
    )
    entry.add_to_hass(hass)
    return entry


def _runtime(
    hass: HomeAssistant,
    entry: MockConfigEntry,
) -> GroupAlarmRuntimeData:
    """Attach two contrasting organization snapshots."""
    client = AsyncMock(spec=GroupAlarmClient)
    user = GroupAlarmUser(id=654_321_987)
    coordinator = GroupAlarmCoordinator(
        hass,
        entry,
        client,
        user,
        {
            987_654_321: "Sensitive Organization",
            123_456_789: "Other Sensitive Organization",
        },
        60,
    )
    coordinator.data = GroupAlarmCoordinatorData(
        organizations=(
            OrganizationSnapshot(
                user_id=user.id,
                organization_id=987_654_321,
                organization_name="Sensitive Organization",
                available=True,
                error=None,
                alarm=_alarm(),
            ),
            OrganizationSnapshot(
                user_id=user.id,
                organization_id=123_456_789,
                organization_name="Other Sensitive Organization",
                available=False,
                error=OrganizationError.TRANSPORT,
                alarm=None,
            ),
        )
    )
    coordinator._last_successful_update = datetime(2026, 7, 27, 13, tzinfo=UTC)
    return GroupAlarmRuntimeData(
        client=client,
        user=user,
        coordinator=coordinator,
    )


async def test_diagnostics_expose_only_pseudonyms_and_state_flags(
    hass: HomeAssistant,
) -> None:
    """Sensitive configuration and alarm content never enter diagnostics."""
    entry = _entry(hass)
    entry.runtime_data = _runtime(hass, entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    serialized = json.dumps(diagnostics, sort_keys=True)

    assert diagnostics["integration"] == {
        "version": "0.5.1",
        "config_entry_version": 3,
        "scan_interval_seconds": 60,
        "organization_count": 2,
        "arrival_duration_count": 1,
        "feedback_device_configured": True,
    }
    assert diagnostics["user"].startswith("user_")
    assert diagnostics["last_successful_update"] == "2026-07-27T13:00:00+00:00"
    assert diagnostics["organizations"][0]["organization"].startswith("organization_")
    assert diagnostics["organizations"][0]["alarm"].startswith("alarm_")
    assert diagnostics["organizations"][0]["event"].startswith("event_")
    assert diagnostics["organizations"][0]["location_available"] is True
    assert diagnostics["organizations"][1]["error"] == "transport"

    for sensitive in (
        "real-looking-groupalarm-secret",
        "Sensitive",
        "Alice",
        "987654321",
        "123456789",
        "876543210",
        "765432109",
        "543219876",
        "50.123456",
        "6.654321",
    ):
        assert sensitive not in serialized


async def test_diagnostic_pseudonyms_are_stable_and_entry_local(
    hass: HomeAssistant,
) -> None:
    """Repeated exports are comparable without creating global identifiers."""
    first = _entry(hass)
    first.runtime_data = _runtime(hass, first)
    first_result = await async_get_config_entry_diagnostics(hass, first)

    repeated = await async_get_config_entry_diagnostics(hass, first)
    assert repeated["user"] == first_result["user"]
    assert (
        repeated["organizations"][0]["organization"]
        == first_result["organizations"][0]["organization"]
    )

    second = _entry(hass)
    second.runtime_data = _runtime(hass, second)
    second_result = await async_get_config_entry_diagnostics(hass, second)
    assert second_result["user"] != first_result["user"]


async def test_diagnostics_handle_malformed_non_sensitive_options(
    hass: HomeAssistant,
) -> None:
    """Diagnostics remain available when stored optional values are malformed."""
    entry = _entry(hass)
    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_SCAN_INTERVAL: True,
            CONF_ORGANIZATION_DURATIONS: "invalid",
            CONF_FEEDBACK_DEVICE_ID: False,
        },
    )
    entry.runtime_data = _runtime(hass, entry)
    entry.runtime_data.coordinator._last_successful_update = None

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["integration"]["scan_interval_seconds"] is None
    assert diagnostics["integration"]["arrival_duration_count"] == 0
    assert diagnostics["integration"]["feedback_device_configured"] is False
    assert diagnostics["last_successful_update"] is None
