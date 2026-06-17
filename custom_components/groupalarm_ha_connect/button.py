from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GroupAlarmCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinators: dict[int, GroupAlarmCoordinator] = hass.data[DOMAIN][entry.entry_id]
    entities: list[GroupAlarmFeedbackButton] = []
    for coordinator in coordinators.values():
        entities.extend([
            GroupAlarmFeedbackButton(coordinator, entry, "komme", "Komme", True),
            GroupAlarmFeedbackButton(coordinator, entry, "komme_nicht", "Komme nicht", False),
        ])
    async_add_entities(entities)


class GroupAlarmFeedbackButton(CoordinatorEntity[GroupAlarmCoordinator], ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: GroupAlarmCoordinator, entry: ConfigEntry, key: str, name: str, response: bool) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{coordinator.organization_id}_feedback_{key}"
        self._attr_name = name
        self._attr_device_info = coordinator.device_info
        self._response = response

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.is_alert_active

    async def async_press(self) -> None:
        await self.coordinator.async_set_feedback(self._response)
