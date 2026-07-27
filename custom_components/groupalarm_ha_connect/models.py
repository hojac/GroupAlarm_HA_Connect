"""Shared typed models for GroupAlarm HA Connect."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .api import GroupAlarmClient, GroupAlarmUser


@dataclass(frozen=True, slots=True)
class GroupAlarmRuntimeData:
    """Resources owned by one loaded config entry."""

    client: GroupAlarmClient
    user: GroupAlarmUser


type GroupAlarmConfigEntry = ConfigEntry[GroupAlarmRuntimeData]


def build_entry_unique_id(user_id: int, organization_ids: tuple[int, ...]) -> str:
    """Build a stable account-and-scope config entry identity."""
    if user_id < 1:
        raise ValueError("user_id must be a positive integer")
    normalized = tuple(sorted(set(organization_ids)))
    if not normalized or any(value < 1 for value in normalized):
        raise ValueError("organization_ids must contain positive integers")
    organization_scope = "-".join(str(value) for value in normalized)
    return f"user_{user_id}_organizations_{organization_scope}"
