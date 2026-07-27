"""Shared Home Assistant entity support."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GroupAlarmCoordinator
from .models import (
    OrganizationSnapshot,
    build_device_identifier,
    build_entity_unique_id,
)


class GroupAlarmEntity(CoordinatorEntity[GroupAlarmCoordinator]):
    """Base entity projecting one normalized organization snapshot."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GroupAlarmCoordinator,
        organization_id: int,
        entity_key: str,
    ) -> None:
        """Initialize stable registry and device identities."""
        super().__init__(coordinator, context=organization_id)
        self.organization_id = organization_id
        self._attr_unique_id = build_entity_unique_id(
            coordinator.user.id,
            organization_id,
            entity_key,
        )
        self._attr_device_info = DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    build_device_identifier(
                        coordinator.user.id,
                        organization_id,
                    ),
                )
            },
            name=(
                "GroupAlarm HA Connect "
                f"{coordinator.organization_names[organization_id]}"
            ),
            manufacturer="GroupAlarm",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def snapshot(self) -> OrganizationSnapshot:
        """Return this entity's immutable organization snapshot."""
        return self.coordinator.snapshot(self.organization_id)

    @property
    def available(self) -> bool:
        """Expose coordinator and organization-scoped availability."""
        return super().available and self.snapshot.available
