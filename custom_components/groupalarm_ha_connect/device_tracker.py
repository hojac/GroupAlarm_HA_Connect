from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GroupAlarmCoordinator


def _get_path(data: dict[str, Any] | None, *keys: str, default: Any = None) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinators: dict[int, GroupAlarmCoordinator] = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(GroupAlarmLocationTracker(coordinator, entry) for coordinator in coordinators.values())


class GroupAlarmLocationTracker(CoordinatorEntity[GroupAlarmCoordinator], TrackerEntity):
    _attr_name = "Einsatzort"
    _attr_has_entity_name = True
    _attr_source_type = SourceType.GPS

    def __init__(self, coordinator: GroupAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{coordinator.organization_id}_location_tracker"
        self._attr_device_info = coordinator.device_info

    @property
    def latitude(self) -> float | None:
        value = _get_path(
            self.coordinator.alarm,
            "optionalContent",
            "location",
            "latitude",
            default=_get_path(self.coordinator.alarm, "optionalContent", "latitude"),
        )
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def longitude(self) -> float | None:
        value = _get_path(
            self.coordinator.alarm,
            "optionalContent",
            "location",
            "longitude",
            default=_get_path(self.coordinator.alarm, "optionalContent", "longitude"),
        )
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
