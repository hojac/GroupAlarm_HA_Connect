"""Focused tests for immutable domain state and entity projections."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.groupalarm_ha_connect.api import (
    GroupAlarmClient,
    GroupAlarmUser,
)
from custom_components.groupalarm_ha_connect.binary_sensor import (
    GroupAlarmActiveAlertBinarySensor,
)
from custom_components.groupalarm_ha_connect.const import (
    CONF_ORGANIZATION_DURATIONS,
    CONF_ORGANIZATION_IDS,
    CONF_ORGANIZATION_NAMES,
    CONF_USER_ID,
    DOMAIN,
)
from custom_components.groupalarm_ha_connect.coordinator import GroupAlarmCoordinator
from custom_components.groupalarm_ha_connect.device_tracker import (
    GroupAlarmLocationTracker,
)
from custom_components.groupalarm_ha_connect.models import (
    AlarmActivity,
    AlarmLocation,
    AlarmVisibility,
    DeadlineStatus,
    FeedbackCounts,
    FeedbackEligibility,
    GroupAlarmAlarm,
    GroupAlarmCoordinatorData,
    OrganizationSnapshot,
    PersonalFeedback,
    build_device_identifier,
    build_entity_unique_id,
    build_entry_unique_id,
)
from custom_components.groupalarm_ha_connect.sensor import _alarm_time, _value


def _alarm(
    *,
    activity: AlarmActivity = AlarmActivity.UNKNOWN,
    location: AlarmLocation | None = None,
) -> GroupAlarmAlarm:
    return GroupAlarmAlarm(
        id=11,
        organization_id=7,
        message="Probealarm",
        started_at=datetime(2026, 7, 27, 10, tzinfo=UTC),
        closed_at=None,
        event_id=70,
        event_name="Einsatz",
        event_closed_at=None,
        event_archived=False,
        event_abort_present=False,
        feedback_counts=FeedbackCounts(positive=2, negative=1, unknown=3),
        personal_feedback=PersonalFeedback.POSITIVE,
        personal_feedback_duration=12,
        activity=activity,
        feedback_eligibility=FeedbackEligibility.OPEN,
        deadline_status=DeadlineStatus.ANSWERED,
        location=location,
    )


def _snapshot(alarm: GroupAlarmAlarm | None) -> OrganizationSnapshot:
    return OrganizationSnapshot(
        user_id=41,
        organization_id=7,
        organization_name="Ortswehr",
        available=True,
        error=None,
        alarm=alarm,
    )


def _coordinator(
    hass: HomeAssistant,
    snapshot: OrganizationSnapshot,
) -> GroupAlarmCoordinator:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_TOKEN: "token",
            CONF_USER_ID: 41,
            CONF_ORGANIZATION_IDS: [7],
            CONF_ORGANIZATION_NAMES: {"7": "Ortswehr"},
        },
        options={CONF_ORGANIZATION_DURATIONS: {}},
        unique_id="user_41_organizations_7",
        version=3,
    )
    coordinator = GroupAlarmCoordinator(
        hass,
        entry,
        AsyncMock(spec=GroupAlarmClient),
        GroupAlarmUser(id=41),
        {7: "Ortswehr"},
        60,
    )
    coordinator.data = GroupAlarmCoordinatorData(organizations=(snapshot,))
    return coordinator


def test_snapshot_axes_distinguish_no_alarm_from_visible_alarm() -> None:
    """Every public state axis has an explicit no-alarm projection."""
    empty = _snapshot(None)
    assert empty.visibility is AlarmVisibility.NO_ALARM
    assert empty.activity is AlarmActivity.UNKNOWN
    assert empty.personal_feedback is PersonalFeedback.NO_ALARM
    assert empty.deadline_status is DeadlineStatus.NO_ALARM

    visible = _snapshot(_alarm(activity=AlarmActivity.ACTIVE))
    assert visible.visibility is AlarmVisibility.VISIBLE
    assert visible.activity is AlarmActivity.ACTIVE
    assert visible.personal_feedback is PersonalFeedback.POSITIVE
    assert visible.deadline_status is DeadlineStatus.ANSWERED


def test_coordinator_data_lookup_rejects_unknown_organization() -> None:
    """A missing configured organization is never silently substituted."""
    data = GroupAlarmCoordinatorData(organizations=(_snapshot(None),))
    assert data.for_organization(7).organization_name == "Ortswehr"
    with pytest.raises(KeyError):
        data.for_organization(99)


@pytest.mark.parametrize(
    ("builder", "args"),
    [
        (build_entry_unique_id, (0, (7,))),
        (build_entry_unique_id, (41, ())),
        (build_entry_unique_id, (41, (0, 7))),
        (build_device_identifier, (0, 7)),
        (build_entity_unique_id, (41, 0, "alarm_id")),
        (build_entity_unique_id, (41, 7, "")),
    ],
)
def test_stable_id_builders_reject_unsafe_input(
    builder: object,
    args: tuple[object, ...],
) -> None:
    """Registry identities cannot be built from empty or invalid components."""
    with pytest.raises(ValueError, match="must"):
        builder(*args)  # type: ignore[operator]


def test_entry_unique_id_normalizes_order_and_duplicates() -> None:
    """Equivalent organization scopes always produce one config identity."""
    assert build_entry_unique_id(41, (12, 7, 12)) == "user_41_organizations_7-12"


def test_sensor_values_cover_alarm_and_no_alarm_projections() -> None:
    """Sensors expose only normalized fields and return None otherwise."""
    empty = _snapshot(None)
    alarm = _alarm()
    visible = _snapshot(alarm)

    assert _alarm_time(None) is None
    assert _value(empty, "user_id") == 41
    assert _value(empty, "my_feedback") == PersonalFeedback.NO_ALARM.value
    assert _value(empty, "alarm_id") is None

    expected = {
        "alarm_id": 11,
        "message": "Probealarm",
        "start": alarm.started_at,
        "event": "Einsatz",
        "feedback_positive": 2,
        "feedback_negative": 1,
        "feedback_unknown": 3,
    }
    for key, value in expected.items():
        assert _value(visible, key) == value
    assert _value(visible, "alarm_time") == _alarm_time(alarm.started_at)
    assert _value(visible, "unsupported") is None


def test_activity_and_location_entities_preserve_unknown_state(
    hass: HomeAssistant,
) -> None:
    """Binary and GPS entities keep unknown evidence unavailable."""
    unknown = _snapshot(_alarm())
    coordinator = _coordinator(hass, unknown)
    activity = GroupAlarmActiveAlertBinarySensor(coordinator, 7)
    tracker = GroupAlarmLocationTracker(coordinator, 7)

    assert activity.is_on is None
    assert tracker.available is False
    assert tracker.latitude is None
    assert tracker.longitude is None

    located_alarm = replace(
        unknown.alarm,
        activity=AlarmActivity.ACTIVE,
        location=AlarmLocation(
            address="Musterstraße",
            latitude=52.1,
            longitude=13.2,
        ),
    )
    assert located_alarm is not None
    located = replace(unknown, alarm=located_alarm)
    coordinator.data = GroupAlarmCoordinatorData(organizations=(located,))
    assert activity.is_on is True
    assert tracker.available is True
    assert tracker.latitude == 52.1
    assert tracker.longitude == 13.2

    inactive_alarm = replace(located_alarm, activity=AlarmActivity.INACTIVE)
    coordinator.data = GroupAlarmCoordinatorData(
        organizations=(replace(located, alarm=inactive_alarm),)
    )
    assert activity.is_on is False

    coordinator.data = GroupAlarmCoordinatorData(organizations=(_snapshot(None),))
    assert tracker.latitude is None
    assert tracker.longitude is None
