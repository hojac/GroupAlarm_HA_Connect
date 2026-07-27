"""Tests for config entry setup and migration."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.groupalarm_ha_connect import (
    async_migrate_entry,
    async_setup_entry,
)
from custom_components.groupalarm_ha_connect.api import (
    GroupAlarmAuthenticationError,
    GroupAlarmTransportError,
    GroupAlarmUser,
)
from custom_components.groupalarm_ha_connect.const import (
    CONF_ORGANIZATION_DURATIONS,
    CONF_ORGANIZATION_IDS,
    CONF_ORGANIZATION_NAMES,
    CONF_SCAN_INTERVAL,
    CONF_USER_ID,
    DOMAIN,
    LEGACY_CONF_ORGANIZATION_ID,
    LEGACY_CONF_PAT,
)


def _entry(*, version: int = 3) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="GroupAlarm HA Connect",
        data={
            CONF_TOKEN: "token",
            CONF_USER_ID: 41,
            CONF_ORGANIZATION_IDS: [7],
            CONF_ORGANIZATION_NAMES: {"7": "Alpha"},
        },
        options={
            CONF_SCAN_INTERVAL: 60,
            CONF_ORGANIZATION_DURATIONS: {},
        },
        unique_id="user_41_organizations_7",
        version=version,
    )


async def test_setup_uses_runtime_data_and_backfills_identity(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry,
        data={
            CONF_TOKEN: "token",
            CONF_ORGANIZATION_IDS: [7],
            CONF_ORGANIZATION_NAMES: {"7": "Alpha"},
        },
        unique_id=None,
    )
    with patch(
        "custom_components.groupalarm_ha_connect."
        "GroupAlarmClient.async_get_current_user",
        new_callable=AsyncMock,
        return_value=GroupAlarmUser(id=41),
    ):
        assert await async_setup_entry(hass, entry) is True

    assert entry.runtime_data.user.id == 41
    assert entry.data[CONF_USER_ID] == 41
    assert entry.unique_id == "user_41_organizations_7"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (GroupAlarmAuthenticationError(401), ConfigEntryAuthFailed),
        (GroupAlarmTransportError("offline"), ConfigEntryNotReady),
    ],
)
async def test_setup_translates_client_errors(
    hass: HomeAssistant,
    error: Exception,
    expected: type[Exception],
) -> None:
    entry = _entry()
    with (
        patch(
            "custom_components.groupalarm_ha_connect."
            "GroupAlarmClient.async_get_current_user",
            new_callable=AsyncMock,
            side_effect=error,
        ),
        pytest.raises(expected),
    ):
        await async_setup_entry(hass, entry)


async def test_setup_rejects_token_for_different_account(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    with (
        patch(
            "custom_components.groupalarm_ha_connect."
            "GroupAlarmClient.async_get_current_user",
            new_callable=AsyncMock,
            return_value=GroupAlarmUser(id=99),
        ),
        pytest.raises(ConfigEntryAuthFailed),
    ):
        await async_setup_entry(hass, entry)


async def test_migrate_legacy_single_organization_entry(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Legacy",
        data={
            LEGACY_CONF_PAT: "legacy-token",
            LEGACY_CONF_ORGANIZATION_ID: 7,
            CONF_ORGANIZATION_NAMES: {"7": "Alpha"},
            CONF_SCAN_INTERVAL: 75,
        },
        options={
            CONF_SCAN_INTERVAL: 60,
            CONF_ORGANIZATION_DURATIONS: {},
        },
        unique_id="user_0_token_deadbeef_orgs_7",
        version=2,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    assert entry.version == 3
    assert entry.unique_id is None
    assert entry.data == {
        CONF_TOKEN: "legacy-token",
        CONF_ORGANIZATION_IDS: [7],
        CONF_ORGANIZATION_NAMES: {"7": "Alpha"},
    }
    assert entry.options == {
        CONF_SCAN_INTERVAL: 60,
        CONF_ORGANIZATION_DURATIONS: {},
    }


async def test_migration_rejects_future_version(
    hass: HomeAssistant,
) -> None:
    entry = _entry(version=99)

    assert await async_migrate_entry(hass, entry) is False
