"""Transport-layer models for the GroupAlarm API."""

from __future__ import annotations

from dataclasses import dataclass

type JsonValue = str | int | float | bool | None | list[JsonValue] | JsonObject
type JsonObject = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class GroupAlarmUser:
    """Minimal non-sensitive representation of the current user."""

    id: int


@dataclass(frozen=True, slots=True)
class GroupAlarmOrganization:
    """Organization available to the current user."""

    id: int
    name: str


@dataclass(frozen=True, slots=True)
class GroupAlarmAppDevice:
    """Reduced app-device representation without push credentials."""

    id: int
    owner_id: int
    name: str
    active: bool
    is_main_device: bool


@dataclass(frozen=True, slots=True)
class GroupAlarmAlarmPage:
    """Validated alarm-list response."""

    alarms: tuple[JsonObject, ...]
    total_alarms: int
