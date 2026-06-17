from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GroupAlarmCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinators: dict[int, GroupAlarmCoordinator] = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(GroupAlarmActiveAlertBinarySensor(coordinator, entry) for coordinator in coordinators.values())


class GroupAlarmActiveAlertBinarySensor(CoordinatorEntity[GroupAlarmCoordinator], BinarySensorEntity):
    _attr_name = "Aktive Alarmierung"
    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: GroupAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{coordinator.organization_id}_active_alert"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        return self.coordinator.is_alert_active
