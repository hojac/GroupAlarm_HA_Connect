"""Tests for config entry setup and migration."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.groupalarm_ha_connect import (
    _async_reload_entry,
    _organization_names,
    _registry_organization_id,
    async_migrate_entry,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.groupalarm_ha_connect.api import (
    GroupAlarmAuthenticationError,
    GroupAlarmOrganization,
    GroupAlarmPermissionError,
    GroupAlarmTransportError,
    GroupAlarmUser,
)
from custom_components.groupalarm_ha_connect.const import (
    CONF_FEEDBACK_DEVICE_ID,
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
    with (
        patch(
            "custom_components.groupalarm_ha_connect."
            "GroupAlarmClient.async_get_current_user",
            new_callable=AsyncMock,
            return_value=GroupAlarmUser(id=41),
        ),
        patch(
            "custom_components.groupalarm_ha_connect."
            "GroupAlarmClient.async_get_organizations",
            new_callable=AsyncMock,
            return_value=(GroupAlarmOrganization(id=7, name="Alpha"),),
        ),
        patch(
            "custom_components.groupalarm_ha_connect."
            "GroupAlarmCoordinator.async_config_entry_first_refresh",
            new_callable=AsyncMock,
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=AsyncMock,
        ),
    ):
        assert await async_setup_entry(hass, entry) is True

    assert entry.runtime_data.user.id == 41
    assert entry.runtime_data.coordinator.user.id == 41
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


def test_organization_names_prefer_current_and_keep_inaccessible_scope() -> None:
    """Current labels win while stored names preserve inaccessible scopes."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ORGANIZATION_IDS: [12, 7],
            CONF_ORGANIZATION_NAMES: {
                7: "Stored Alpha",
                "12": "Stored Bravo",
            },
        },
    )
    assert _organization_names(
        entry,
        (GroupAlarmOrganization(id=7, name="Current Alpha"),),
    ) == {7: "Current Alpha", 12: "Stored Bravo"}

    invalid_names = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ORGANIZATION_IDS: [12, 7],
            CONF_ORGANIZATION_NAMES: "invalid",
        },
    )
    assert _organization_names(invalid_names, ()) == {7: "7", 12: "12"}


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("other", None),
        ("entry_", None),
        ("entry_x_alarm_id", None),
        ("entry_0_alarm_id", None),
        ("entry_7_alarm_id", (7, "alarm_id")),
        ("user_41_organization_12_message", (12, "message")),
    ],
)
def test_registry_identifier_parser(
    identifier: str,
    expected: tuple[int, str] | None,
) -> None:
    """Only valid legacy or current identities owned by the entry are parsed."""
    assert (
        _registry_organization_id(
            identifier,
            entry_id="entry",
            user_id=41,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (GroupAlarmAuthenticationError(401), ConfigEntryAuthFailed),
        (GroupAlarmPermissionError(403), ConfigEntryAuthFailed),
        (GroupAlarmTransportError("offline"), ConfigEntryNotReady),
    ],
)
async def test_setup_translates_organization_fetch_errors(
    hass: HomeAssistant,
    error: Exception,
    expected: type[Exception],
) -> None:
    """Organization loading uses the same safe retry/auth split as user loading."""
    entry = _entry()
    with (
        patch(
            "custom_components.groupalarm_ha_connect."
            "GroupAlarmClient.async_get_current_user",
            new_callable=AsyncMock,
            return_value=GroupAlarmUser(id=41),
        ),
        patch(
            "custom_components.groupalarm_ha_connect."
            "GroupAlarmClient.async_get_organizations",
            new_callable=AsyncMock,
            side_effect=error,
        ),
        pytest.raises(expected),
    ):
        await async_setup_entry(hass, entry)


async def test_setup_keeps_matching_entry_identity(
    hass: HomeAssistant,
) -> None:
    """An already canonical entry is not rewritten during setup."""
    entry = _entry()
    with (
        patch(
            "custom_components.groupalarm_ha_connect."
            "GroupAlarmClient.async_get_current_user",
            new_callable=AsyncMock,
            return_value=GroupAlarmUser(id=41),
        ),
        patch(
            "custom_components.groupalarm_ha_connect."
            "GroupAlarmClient.async_get_organizations",
            new_callable=AsyncMock,
            return_value=(GroupAlarmOrganization(id=7, name="Alpha"),),
        ),
        patch(
            "custom_components.groupalarm_ha_connect."
            "GroupAlarmCoordinator.async_config_entry_first_refresh",
            new_callable=AsyncMock,
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_update_entry"
        ) as update_entry,
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=AsyncMock,
        ),
    ):
        assert await async_setup_entry(hass, entry)
    update_entry.assert_not_called()


@pytest.mark.parametrize("unloaded", [False, True])
async def test_unload_respects_platform_result(
    hass: HomeAssistant,
    unloaded: bool,
) -> None:
    """Coordinator shutdown occurs only after every platform unloaded."""
    entry = _entry()
    shutdown = AsyncMock()
    entry.runtime_data = SimpleNamespace(
        coordinator=SimpleNamespace(async_shutdown=shutdown)
    )
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
        new=AsyncMock(return_value=unloaded),
    ):
        assert await async_unload_entry(hass, entry) is unloaded
    assert shutdown.await_count == int(unloaded)


async def test_update_listener_reloads_its_entry(
    hass: HomeAssistant,
) -> None:
    """Options updates delegate to Home Assistant's entry reload."""
    entry = _entry()
    with patch.object(
        hass.config_entries,
        "async_reload",
        new=AsyncMock(),
    ) as reload_entry:
        await _async_reload_entry(hass, entry)
    reload_entry.assert_awaited_once_with(entry.entry_id)


async def test_current_version_migration_is_a_noop(
    hass: HomeAssistant,
) -> None:
    """Canonical entries pass migration without a write."""
    entry = _entry()
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_update_entry"
    ) as update_entry:
        assert await async_migrate_entry(hass, entry)
    update_entry.assert_not_called()


@pytest.mark.parametrize(
    "data",
    [
        {LEGACY_CONF_PAT: ""},
        {LEGACY_CONF_PAT: "token"},
        {
            LEGACY_CONF_PAT: "token",
            CONF_ORGANIZATION_IDS: ["invalid"],
        },
        {
            LEGACY_CONF_PAT: "token",
            CONF_ORGANIZATION_IDS: [],
        },
        {
            LEGACY_CONF_PAT: "token",
            CONF_ORGANIZATION_IDS: [0],
        },
    ],
)
async def test_migration_rejects_irrecoverable_legacy_data(
    hass: HomeAssistant,
    data: dict[str, object],
) -> None:
    """Migration fails closed when authentication or scope cannot be recovered."""
    entry = MockConfigEntry(domain=DOMAIN, data=data, version=2)
    assert await async_migrate_entry(hass, entry) is False


async def test_migration_sanitizes_options_and_preserves_valid_device(
    hass: HomeAssistant,
) -> None:
    """Legacy options retain only valid scoped durations and a usable device."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_TOKEN: "token",
            LEGACY_CONF_PAT: "obsolete",
            CONF_ORGANIZATION_IDS: [12, 7, 7],
            CONF_ORGANIZATION_NAMES: "invalid",
            CONF_SCAN_INTERVAL: "invalid",
        },
        options={
            CONF_ORGANIZATION_DURATIONS: {
                "7": 12,
                "12": 181,
                "99": 5,
                "invalid": "invalid",
            },
            CONF_FEEDBACK_DEVICE_ID: 91,
        },
        version=2,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)
    assert entry.data == {
        CONF_TOKEN: "token",
        CONF_ORGANIZATION_IDS: [7, 12],
        CONF_ORGANIZATION_NAMES: {"7": "7", "12": "12"},
    }
    assert entry.options == {
        CONF_SCAN_INTERVAL: 60,
        CONF_ORGANIZATION_DURATIONS: {"7": 12},
        CONF_FEEDBACK_DEVICE_ID: 91,
    }


async def test_migration_normalizes_out_of_range_interval(
    hass: HomeAssistant,
) -> None:
    """Legacy poll intervals outside safe bounds reset to the default."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_TOKEN: "token",
            CONF_ORGANIZATION_IDS: [7],
        },
        options={CONF_SCAN_INTERVAL: 1},
        version=2,
    )
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry)
    assert entry.options[CONF_SCAN_INTERVAL] == 60
