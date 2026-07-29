"""Binary sensors for normalized GroupAlarm state."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GroupAlarmCoordinator
from .entity import GroupAlarmEntity
from .models import AlarmActivity, GroupAlarmConfigEntry

ACTIVE_ALERT_DESCRIPTION = BinarySensorEntityDescription(
    key="active_alert",
    translation_key="active_alert",
    device_class=BinarySensorDeviceClass.RUNNING,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GroupAlarmConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one activity entity per configured organization."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        GroupAlarmActiveAlertBinarySensor(coordinator, organization_id)
        for organization_id in coordinator.organization_names
    )


class GroupAlarmActiveAlertBinarySensor(GroupAlarmEntity, BinarySensorEntity):
    """Represent only evidence-backed alarm activity."""

    entity_description = ACTIVE_ALERT_DESCRIPTION

    def __init__(
        self,
        coordinator: GroupAlarmCoordinator,
        organization_id: int,
    ) -> None:
        """Initialize the activity binary sensor."""
        super().__init__(coordinator, organization_id, self.entity_description.key)

    @property
    def is_on(self) -> bool | None:
        """Return the separately normalized alarm activity."""
        activity = self.snapshot.activity
        if activity is AlarmActivity.ACTIVE:
            return True
        if activity is AlarmActivity.INACTIVE:
            return False
        return None
