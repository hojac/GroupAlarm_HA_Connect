"""Actionable Home Assistant repair issues."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import (
    CONF_FEEDBACK_DEVICE_ID,
    CONF_ORGANIZATION_DURATIONS,
    DOMAIN,
)
from .models import GroupAlarmConfigEntry

ISSUE_INVALID_FEEDBACK_DEVICE = "invalid_feedback_device"


def _issue_id(entry: GroupAlarmConfigEntry) -> str:
    """Return an entry-scoped issue identity."""
    return f"{ISSUE_INVALID_FEEDBACK_DEVICE}_{entry.entry_id}"


def _has_arrival_durations(entry: GroupAlarmConfigEntry) -> bool:
    """Return whether the entry has any duration-dependent feedback."""
    durations = entry.options.get(CONF_ORGANIZATION_DURATIONS)
    return isinstance(durations, dict) and bool(durations)


def _has_valid_feedback_device(entry: GroupAlarmConfigEntry) -> bool:
    """Validate only the persisted device identity shape."""
    device_id = entry.options.get(CONF_FEEDBACK_DEVICE_ID)
    return (
        not isinstance(device_id, bool) and isinstance(device_id, int) and device_id > 0
    )


def async_sync_feedback_device_issue(
    hass: HomeAssistant,
    entry: GroupAlarmConfigEntry,
) -> None:
    """Create or clear the actionable invalid-device repair issue."""
    issue_id = _issue_id(entry)
    if not _has_arrival_durations(entry) or _has_valid_feedback_device(entry):
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return

    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        is_persistent=False,
        issue_domain=DOMAIN,
        severity=ir.IssueSeverity.ERROR,
        translation_key=ISSUE_INVALID_FEEDBACK_DEVICE,
    )
