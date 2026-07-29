"""Privacy-preserving diagnostics for GroupAlarm HA Connect."""

from __future__ import annotations

import hashlib
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    CONF_FEEDBACK_DEVICE_ID,
    CONF_ORGANIZATION_DURATIONS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    INTEGRATION_VERSION,
)
from .models import GroupAlarmConfigEntry, OrganizationSnapshot

_RECOGNIZED_FIELD_PATHS = (
    "alarms[].id",
    "alarms[].organizationID",
    "alarms[].startDate",
    "alarms[].endDate",
    "alarms[].event.id",
    "alarms[].event.organizationID",
    "alarms[].event.endDate",
    "alarms[].event.archived",
    "alarms[].event.abort.time",
    "alarms[].feedbackQuantity.positive",
    "alarms[].feedbackQuantity.negative",
    "alarms[].feedbackQuantity.unknown",
    "alarm.id",
    "alarm.organizationID",
    "alarm.message",
    "alarm.startDate",
    "alarm.endDate",
    "alarm.event.id",
    "alarm.event.name",
    "alarm.event.organizationID",
    "alarm.event.endDate",
    "alarm.event.archived",
    "alarm.event.abort",
    "alarm.optionalContent.address",
    "alarm.optionalContent.coordinateFormat",
    "alarm.optionalContent.latitude",
    "alarm.optionalContent.longitude",
    "alarm.feedback[].alarmID",
    "alarm.feedback[].userID",
    "alarm.feedback[].state",
    "alarm.feedback[].feedback",
    "alarm.feedback[].userDuration",
)


def _pseudonym(entry: GroupAlarmConfigEntry, category: str, value: int) -> str:
    """Return a deterministic entry-local pseudonym."""
    digest = hashlib.sha256(
        f"{entry.entry_id}:{category}:{value}".encode()
    ).hexdigest()[:12]
    return f"{category}_{digest}"


def _snapshot_diagnostics(
    entry: GroupAlarmConfigEntry,
    snapshot: OrganizationSnapshot,
) -> dict[str, Any]:
    """Reduce one snapshot to identifiers and non-content state flags."""
    alarm = snapshot.alarm
    return {
        "organization": _pseudonym(
            entry,
            "organization",
            snapshot.organization_id,
        ),
        "available": snapshot.available,
        "error": snapshot.error.value if snapshot.error is not None else None,
        "alarm_present": alarm is not None,
        "alarm": (_pseudonym(entry, "alarm", alarm.id) if alarm is not None else None),
        "event": (
            _pseudonym(entry, "event", alarm.event_id)
            if alarm is not None and alarm.event_id is not None
            else None
        ),
        "activity": snapshot.activity.value,
        "feedback_eligibility": (
            alarm.feedback_eligibility.value if alarm is not None else "unknown"
        ),
        "personal_feedback": snapshot.personal_feedback.value,
        "deadline_status": snapshot.deadline_status.value,
        "location_available": alarm is not None and alarm.location is not None,
    }


def _configured_duration_count(entry: GroupAlarmConfigEntry) -> int:
    """Return only the number of configured organization durations."""
    durations = entry.options.get(CONF_ORGANIZATION_DURATIONS)
    return len(durations) if isinstance(durations, dict) else 0


def _scan_interval(entry: GroupAlarmConfigEntry) -> int | None:
    """Return a non-sensitive scan interval when it is well formed."""
    value: object = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _feedback_device_configured(entry: GroupAlarmConfigEntry) -> bool:
    """Return only whether a positive device identity is configured."""
    value: object = entry.options.get(CONF_FEEDBACK_DEVICE_ID)
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: GroupAlarmConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics without credentials or personal alarm content."""
    del hass
    runtime = entry.runtime_data
    coordinator = runtime.coordinator
    last_successful_update = coordinator.last_successful_update
    return {
        "integration": {
            "version": INTEGRATION_VERSION,
            "config_entry_version": entry.version,
            "scan_interval_seconds": _scan_interval(entry),
            "organization_count": len(coordinator.data.organizations),
            "arrival_duration_count": _configured_duration_count(entry),
            "feedback_device_configured": _feedback_device_configured(entry),
        },
        "user": _pseudonym(entry, "user", runtime.user.id),
        "last_successful_update": (
            last_successful_update.isoformat()
            if last_successful_update is not None
            else None
        ),
        "organizations": [
            _snapshot_diagnostics(entry, snapshot)
            for snapshot in coordinator.data.organizations
        ],
        "recognized_field_paths": list(_RECOGNIZED_FIELD_PATHS),
    }
