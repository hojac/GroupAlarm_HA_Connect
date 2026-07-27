"""Immutable domain and runtime models for GroupAlarm HA Connect."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry

from .api import GroupAlarmClient, GroupAlarmUser

if TYPE_CHECKING:
    from .coordinator import GroupAlarmCoordinator


class AlarmVisibility(StrEnum):
    """Whether a validated alarm is available for display."""

    NO_ALARM = "no_alarm"
    VISIBLE = "visible"


class AlarmActivity(StrEnum):
    """Evidence-backed activity state of an alarm."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


class FeedbackEligibility(StrEnum):
    """Whether GroupAlarm is proven to accept feedback."""

    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class PersonalFeedback(StrEnum):
    """Server-confirmed feedback of the current user."""

    NO_ALARM = "no_alarm"
    UNKNOWN = "unknown"
    POSITIVE = "komme"
    NEGATIVE = "komme_nicht"


class DeadlineStatus(StrEnum):
    """Evidence-backed feedback-deadline state."""

    NO_ALARM = "no_alarm"
    KNOWN_ACTIVE = "known_active"
    KNOWN_EXPIRED = "known_expired"
    ANSWERED = "answered"
    UNKNOWN = "unknown"


class OrganizationError(StrEnum):
    """Sanitized organization-scoped update error."""

    PERMISSION = "permission"
    RATE_LIMIT = "rate_limit"
    REQUEST = "request"
    RESPONSE = "response"
    SERVER = "server"
    TRANSPORT = "transport"


@dataclass(frozen=True, slots=True)
class FeedbackCounts:
    """Aggregate feedback counts from one alarm."""

    positive: int | None
    negative: int | None
    unknown: int | None


@dataclass(frozen=True, slots=True)
class AlarmLocation:
    """A fixture-proven alarm location."""

    address: str | None
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class AlarmRevision:
    """Small non-payload revision fingerprint from the alarm list."""

    alarm_closed_at: datetime | None
    event_id: int | None
    event_closed_at: datetime | None
    event_archived: bool | None
    event_abort_present: bool
    event_abort_at: datetime | None
    feedback_counts: FeedbackCounts


@dataclass(frozen=True, slots=True)
class AlarmReference:
    """Validated candidate selected from a bounded alarm-list page."""

    id: int
    organization_id: int
    started_at: datetime
    revision: AlarmRevision


@dataclass(frozen=True, slots=True)
class GroupAlarmAlarm:
    """Canonical normalized alarm detail."""

    id: int
    organization_id: int
    message: str
    started_at: datetime
    closed_at: datetime | None
    event_id: int | None
    event_name: str | None
    event_closed_at: datetime | None
    event_archived: bool | None
    event_abort_present: bool
    feedback_counts: FeedbackCounts
    personal_feedback: PersonalFeedback
    personal_feedback_duration: int | None
    activity: AlarmActivity
    feedback_eligibility: FeedbackEligibility
    deadline_status: DeadlineStatus
    location: AlarmLocation | None


@dataclass(frozen=True, slots=True)
class OrganizationSnapshot:
    """Latest normalized state for one configured organization."""

    user_id: int
    organization_id: int
    organization_name: str
    available: bool
    error: OrganizationError | None
    alarm: GroupAlarmAlarm | None

    @property
    def visibility(self) -> AlarmVisibility:
        """Return alarm visibility independently of other state axes."""
        if self.alarm is None:
            return AlarmVisibility.NO_ALARM
        return AlarmVisibility.VISIBLE

    @property
    def activity(self) -> AlarmActivity:
        """Return the evidence-backed activity state."""
        if self.alarm is None:
            return AlarmActivity.UNKNOWN
        return self.alarm.activity

    @property
    def personal_feedback(self) -> PersonalFeedback:
        """Return the current user's confirmed feedback."""
        if self.alarm is None:
            return PersonalFeedback.NO_ALARM
        return self.alarm.personal_feedback

    @property
    def deadline_status(self) -> DeadlineStatus:
        """Return the evidence-backed deadline state."""
        if self.alarm is None:
            return DeadlineStatus.NO_ALARM
        return self.alarm.deadline_status


@dataclass(frozen=True, slots=True)
class GroupAlarmCoordinatorData:
    """Comparable coordinator output containing all organizations."""

    organizations: tuple[OrganizationSnapshot, ...]

    def for_organization(self, organization_id: int) -> OrganizationSnapshot:
        """Return the snapshot for a configured organization."""
        for snapshot in self.organizations:
            if snapshot.organization_id == organization_id:
                return snapshot
        raise KeyError(organization_id)


@dataclass(frozen=True, slots=True)
class GroupAlarmRuntimeData:
    """Resources owned by one loaded config entry."""

    client: GroupAlarmClient
    user: GroupAlarmUser
    coordinator: GroupAlarmCoordinator


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


def build_device_identifier(user_id: int, organization_id: int) -> str:
    """Build a stable device identifier."""
    if min(user_id, organization_id) < 1:
        raise ValueError("device identifiers must be positive integers")
    return f"user_{user_id}_organization_{organization_id}"


def build_entity_unique_id(
    user_id: int,
    organization_id: int,
    entity_key: str,
) -> str:
    """Build a stable entity identity independent of token and names."""
    if min(user_id, organization_id) < 1:
        raise ValueError("entity identifiers must be positive integers")
    if not entity_key:
        raise ValueError("entity_key must not be empty")
    return f"{build_device_identifier(user_id, organization_id)}_{entity_key}"
