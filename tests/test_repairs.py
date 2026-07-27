"""Tests for actionable Home Assistant repair issues."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.groupalarm_ha_connect.const import (
    CONF_FEEDBACK_DEVICE_ID,
    CONF_ORGANIZATION_DURATIONS,
    DOMAIN,
)
from custom_components.groupalarm_ha_connect.repairs import (
    ISSUE_INVALID_FEEDBACK_DEVICE,
    async_sync_feedback_device_issue,
)


@pytest.mark.parametrize("device_id", [None, True, 0, -1, "42"])
def test_invalid_feedback_device_creates_actionable_issue(
    hass: HomeAssistant,
    device_id: object,
) -> None:
    """A duration without a usable persisted device can be fixed in options."""
    options: dict[str, object] = {
        CONF_ORGANIZATION_DURATIONS: {"7": 12},
    }
    if device_id is not None:
        options[CONF_FEEDBACK_DEVICE_ID] = device_id
    entry = MockConfigEntry(domain=DOMAIN, options=options)
    entry.add_to_hass(hass)

    async_sync_feedback_device_issue(hass, entry)

    issue = ir.async_get(hass).async_get_issue(
        DOMAIN,
        f"{ISSUE_INVALID_FEEDBACK_DEVICE}_{entry.entry_id}",
    )
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.is_persistent is False
    assert issue.severity is ir.IssueSeverity.ERROR
    assert issue.translation_key == ISSUE_INVALID_FEEDBACK_DEVICE


def test_valid_or_unused_feedback_device_clears_issue(
    hass: HomeAssistant,
) -> None:
    """Reload after correcting options removes the repair automatically."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        options={
            CONF_ORGANIZATION_DURATIONS: {"7": 12},
        },
    )
    entry.add_to_hass(hass)
    issue_id = f"{ISSUE_INVALID_FEEDBACK_DEVICE}_{entry.entry_id}"

    async_sync_feedback_device_issue(hass, entry)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_ORGANIZATION_DURATIONS: {"7": 12},
            CONF_FEEDBACK_DEVICE_ID: 42,
        },
    )
    async_sync_feedback_device_issue(hass, entry)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None

    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_ORGANIZATION_DURATIONS: {},
            CONF_FEEDBACK_DEVICE_ID: -1,
        },
    )
    async_sync_feedback_device_issue(hass, entry)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
