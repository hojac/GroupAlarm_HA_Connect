"""Read-only sensors for normalized GroupAlarm state."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import GroupAlarmCoordinator
from .entity import GroupAlarmEntity
from .models import (
    DeadlineStatus,
    GroupAlarmConfigEntry,
    OrganizationSnapshot,
    PersonalFeedback,
)

type SensorValue = str | int | float | Decimal | datetime | None


SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="alarm_id",
        translation_key="alarm_id",
    ),
    SensorEntityDescription(
        key="message",
        translation_key="message",
    ),
    SensorEntityDescription(
        key="start",
        translation_key="start",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(
        key="alarm_time",
        translation_key="alarm_time",
    ),
    SensorEntityDescription(
        key="feedback_deadline",
        translation_key="feedback_deadline",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(
        key="feedback_countdown",
        translation_key="feedback_countdown",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="deadline_status",
        translation_key="deadline_status",
        device_class=SensorDeviceClass.ENUM,
        options=[state.value for state in DeadlineStatus],
    ),
    SensorEntityDescription(
        key="event",
        translation_key="event",
    ),
    SensorEntityDescription(
        key="feedback_positive",
        translation_key="feedback_positive",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="feedback_negative",
        translation_key="feedback_negative",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="feedback_unknown",
        translation_key="feedback_unknown",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="my_feedback",
        translation_key="my_feedback",
        device_class=SensorDeviceClass.ENUM,
        options=[state.value for state in PersonalFeedback],
    ),
    SensorEntityDescription(
        key="user_id",
        translation_key="user_id",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)


def _alarm_time(value: datetime | None) -> str | None:
    """Format the compatibility alarm-time sensor in local time."""
    if value is None:
        return None
    return dt_util.as_local(value).strftime("%d.%m.%Y %H:%M")


def _value(snapshot: OrganizationSnapshot, key: str) -> SensorValue:
    """Project one sensor value from normalized state."""
    alarm = snapshot.alarm
    if key == "user_id":
        return snapshot.user_id
    if key == "my_feedback":
        return snapshot.personal_feedback.value
    if key == "deadline_status":
        return snapshot.deadline_status.value
    if alarm is None:
        return None
    if key == "alarm_id":
        return alarm.id
    if key == "message":
        return alarm.message
    if key == "start":
        return alarm.started_at
    if key == "alarm_time":
        return _alarm_time(alarm.started_at)
    if key == "feedback_deadline":
        return alarm.feedback_deadline
    if key == "event":
        return alarm.event_name
    if key == "feedback_positive":
        return alarm.feedback_counts.positive
    if key == "feedback_negative":
        return alarm.feedback_counts.negative
    if key == "feedback_unknown":
        return alarm.feedback_counts.unknown
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GroupAlarmConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one sensor set per configured organization."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        GroupAlarmSensor(coordinator, organization_id, description)
        for organization_id in coordinator.organization_names
        for description in SENSORS
    )


class GroupAlarmSensor(GroupAlarmEntity, SensorEntity):
    """A sensor backed only by coordinator memory."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        coordinator: GroupAlarmCoordinator,
        organization_id: int,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize a normalized GroupAlarm sensor."""
        super().__init__(coordinator, organization_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> SensorValue:
        """Return the state without I/O."""
        if self.entity_description.key == "feedback_countdown":
            return self.coordinator.feedback_countdown(self.organization_id)
        return _value(self.snapshot, self.entity_description.key)
