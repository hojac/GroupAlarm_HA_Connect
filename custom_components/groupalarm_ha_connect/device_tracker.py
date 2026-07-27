"""Alarm-location tracker backed by normalized coordinates."""

from __future__ import annotations

from homeassistant.components.device_tracker.const import SourceType
from homeassistant.components.device_tracker.entity import TrackerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GroupAlarmCoordinator
from .entity import GroupAlarmEntity
from .models import GroupAlarmConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GroupAlarmConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one location tracker per configured organization."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        GroupAlarmLocationTracker(coordinator, organization_id)
        for organization_id in coordinator.organization_names
    )


class GroupAlarmLocationTracker(GroupAlarmEntity, TrackerEntity):
    """Expose a GPS location only when both coordinates are proven."""

    _attr_translation_key = "incident_location"
    _attr_source_type = SourceType.GPS

    def __init__(
        self,
        coordinator: GroupAlarmCoordinator,
        organization_id: int,
    ) -> None:
        """Initialize the alarm location tracker."""
        super().__init__(coordinator, organization_id, "location_tracker")

    @property
    def available(self) -> bool:
        """Keep the tracker unavailable without a normalized location."""
        return (
            super().available
            and self.snapshot.alarm is not None
            and self.snapshot.alarm.location is not None
        )

    @property
    def latitude(self) -> float | None:
        """Return validated latitude."""
        alarm = self.snapshot.alarm
        if alarm is None or alarm.location is None:
            return None
        return alarm.location.latitude

    @property
    def longitude(self) -> float | None:
        """Return validated longitude."""
        alarm = self.snapshot.alarm
        if alarm is None or alarm.location is None:
            return None
        return alarm.location.longitude
