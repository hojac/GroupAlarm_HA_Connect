"""Tests for GroupAlarm configuration flows."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    SOURCE_USER,
)
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.groupalarm_ha_connect.api import (
    GroupAlarmAppDevice,
    GroupAlarmAuthenticationError,
    GroupAlarmOrganization,
    GroupAlarmTransportError,
    GroupAlarmUser,
)
from custom_components.groupalarm_ha_connect.config_flow import (
    CONF_ARRIVAL_DURATION,
)
from custom_components.groupalarm_ha_connect.const import (
    CONF_FEEDBACK_DEVICE_ID,
    CONF_ORGANIZATION_DURATIONS,
    CONF_ORGANIZATION_IDS,
    CONF_ORGANIZATION_NAMES,
    CONF_SCAN_INTERVAL,
    CONF_USER_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from custom_components.groupalarm_ha_connect.models import build_entry_unique_id

USER = GroupAlarmUser(id=41)
ORGANIZATIONS = (
    GroupAlarmOrganization(id=7, name="Alpha"),
    GroupAlarmOrganization(id=12, name="Bravo"),
)


@pytest.fixture
def mock_groupalarm() -> Generator[dict[str, AsyncMock]]:
    """Mock all GroupAlarm calls made from a flow."""
    with (
        patch(
            "custom_components.groupalarm_ha_connect.config_flow."
            "GroupAlarmClient.async_get_current_user",
            new_callable=AsyncMock,
            return_value=USER,
        ) as current_user,
        patch(
            "custom_components.groupalarm_ha_connect.config_flow."
            "GroupAlarmClient.async_get_organizations",
            new_callable=AsyncMock,
            return_value=ORGANIZATIONS,
        ) as organizations,
        patch(
            "custom_components.groupalarm_ha_connect.config_flow."
            "GroupAlarmClient.async_get_app_devices",
            new_callable=AsyncMock,
            return_value=(
                GroupAlarmAppDevice(
                    id=91,
                    owner_id=41,
                    name="Phone",
                    active=True,
                    is_main_device=True,
                ),
            ),
        ) as devices,
    ):
        yield {
            "current_user": current_user,
            "organizations": organizations,
            "devices": devices,
        }


def _entry(
    *,
    organizations: list[int] | None = None,
    token: str = "old-token",
) -> MockConfigEntry:
    organization_ids = organizations or [7]
    names = {str(value): f"Org {value}" for value in organization_ids}
    return MockConfigEntry(
        domain=DOMAIN,
        title="GroupAlarm HA Connect",
        data={
            CONF_TOKEN: token,
            CONF_USER_ID: USER.id,
            CONF_ORGANIZATION_IDS: organization_ids,
            CONF_ORGANIZATION_NAMES: names,
        },
        options={
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
            CONF_ORGANIZATION_DURATIONS: {},
        },
        unique_id=build_entry_unique_id(USER.id, tuple(organization_ids)),
        version=3,
    )


async def _start_user_flow(hass: HomeAssistant) -> dict[str, object]:
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )


async def _submit_account(
    hass: HomeAssistant,
    flow_id: str,
    *,
    token: str = "valid-token",
    scan_interval: int = DEFAULT_SCAN_INTERVAL,
) -> dict[str, object]:
    return await hass.config_entries.flow.async_configure(
        flow_id,
        {
            CONF_TOKEN: token,
            CONF_SCAN_INTERVAL: scan_interval,
        },
    )


async def test_user_flow_creates_stable_scoped_entry(
    hass: HomeAssistant,
    mock_groupalarm: dict[str, AsyncMock],
) -> None:
    result = await _start_user_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await _submit_account(hass, result["flow_id"])
    assert result["step_id"] == "organizations"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_ORGANIZATION_IDS: ["7"]},
    )
    assert result["step_id"] == "arrival_times"
    assert result["description_placeholders"] == {"organization": "Alpha"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "GroupAlarm HA Connect Alpha"
    assert result["data"] == {
        CONF_TOKEN: "valid-token",
        CONF_USER_ID: 41,
        CONF_ORGANIZATION_IDS: [7],
        CONF_ORGANIZATION_NAMES: {"7": "Alpha"},
    }
    assert result["options"] == {
        CONF_SCAN_INTERVAL: 60,
        CONF_ORGANIZATION_DURATIONS: {},
    }
    assert result["result"].unique_id == "user_41_organizations_7"


@pytest.mark.parametrize(
    ("side_effect", "expected_error"),
    [
        (GroupAlarmAuthenticationError(401), "invalid_auth"),
        (GroupAlarmTransportError("offline"), "cannot_connect"),
    ],
)
async def test_user_flow_maps_connection_errors(
    hass: HomeAssistant,
    mock_groupalarm: dict[str, AsyncMock],
    side_effect: Exception,
    expected_error: str,
) -> None:
    mock_groupalarm["current_user"].side_effect = side_effect
    result = await _start_user_flow(hass)

    result = await _submit_account(hass, result["flow_id"])

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": expected_error}


async def test_user_flow_rejects_account_without_organizations(
    hass: HomeAssistant,
    mock_groupalarm: dict[str, AsyncMock],
) -> None:
    mock_groupalarm["organizations"].return_value = ()
    result = await _start_user_flow(hass)

    result = await _submit_account(hass, result["flow_id"])

    assert result["errors"] == {"base": "no_organizations"}


async def test_user_flow_rejects_overlapping_scope(
    hass: HomeAssistant,
    mock_groupalarm: dict[str, AsyncMock],
) -> None:
    _entry(organizations=[7]).add_to_hass(hass)
    result = await _start_user_flow(hass)
    result = await _submit_account(hass, result["flow_id"])

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_ORGANIZATION_IDS: ["7", "12"]},
    )

    assert result["step_id"] == "organizations"
    assert result["errors"] == {"base": "organization_already_configured"}


async def test_interval_and_duration_bounds_are_enforced(
    hass: HomeAssistant,
    mock_groupalarm: dict[str, AsyncMock],
) -> None:
    result = await _start_user_flow(hass)
    schema = result["data_schema"]
    with pytest.raises(vol.Invalid):
        schema({CONF_TOKEN: "token", CONF_SCAN_INTERVAL: 29})
    with pytest.raises(vol.Invalid):
        schema({CONF_TOKEN: "token", CONF_SCAN_INTERVAL: 901})
    assert (
        schema({CONF_TOKEN: "token", CONF_SCAN_INTERVAL: 30})[CONF_SCAN_INTERVAL] == 30
    )

    result = await _submit_account(hass, result["flow_id"])
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_ORGANIZATION_IDS: ["7"]},
    )
    duration_schema = result["data_schema"]
    with pytest.raises(vol.Invalid):
        duration_schema({CONF_ARRIVAL_DURATION: 0})
    with pytest.raises(vol.Invalid):
        duration_schema({CONF_ARRIVAL_DURATION: 181})
    assert duration_schema({CONF_ARRIVAL_DURATION: 180})[CONF_ARRIVAL_DURATION] == 180


async def test_timed_feedback_requires_explicit_active_device(
    hass: HomeAssistant,
    mock_groupalarm: dict[str, AsyncMock],
) -> None:
    result = await _start_user_flow(hass)
    result = await _submit_account(hass, result["flow_id"])
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_ORGANIZATION_IDS: ["7"]},
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_ARRIVAL_DURATION: 12},
    )
    assert result["step_id"] == "feedback_device"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_FEEDBACK_DEVICE_ID: "91"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {
        CONF_SCAN_INTERVAL: 60,
        CONF_ORGANIZATION_DURATIONS: {"7": 12},
        CONF_FEEDBACK_DEVICE_ID: 91,
    }


async def test_multiple_organizations_have_independent_duration_steps(
    hass: HomeAssistant,
    mock_groupalarm: dict[str, AsyncMock],
) -> None:
    result = await _start_user_flow(hass)
    result = await _submit_account(hass, result["flow_id"])
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_ORGANIZATION_IDS: ["7", "12"]},
    )
    assert result["description_placeholders"] == {"organization": "Alpha"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {},
    )
    assert result["description_placeholders"] == {"organization": "Bravo"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ORGANIZATION_IDS] == [7, 12]
    assert result["result"].unique_id == "user_41_organizations_7-12"


async def test_timed_feedback_blocks_when_no_active_device_exists(
    hass: HomeAssistant,
    mock_groupalarm: dict[str, AsyncMock],
) -> None:
    mock_groupalarm["devices"].return_value = (
        GroupAlarmAppDevice(
            id=91,
            owner_id=41,
            name="Old phone",
            active=False,
            is_main_device=False,
        ),
    )
    result = await _start_user_flow(hass)
    result = await _submit_account(hass, result["flow_id"])
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_ORGANIZATION_IDS: ["7"]},
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_ARRIVAL_DURATION: 12},
    )

    assert result["step_id"] == "feedback_device"
    assert result["errors"] == {"base": "no_active_devices"}


async def test_reauth_updates_token_for_same_account(
    hass: HomeAssistant,
    mock_groupalarm: dict[str, AsyncMock],
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_REAUTH,
            "entry_id": entry.entry_id,
            "unique_id": entry.unique_id,
        },
        data=entry.data,
    )
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_TOKEN: "new-token"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_TOKEN] == "new-token"
    assert entry.unique_id == "user_41_organizations_7"


async def test_reauth_rejects_different_account(
    hass: HomeAssistant,
    mock_groupalarm: dict[str, AsyncMock],
) -> None:
    mock_groupalarm["current_user"].return_value = GroupAlarmUser(id=99)
    entry = _entry()
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_REAUTH,
            "entry_id": entry.entry_id,
            "unique_id": entry.unique_id,
        },
        data=entry.data,
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_TOKEN: "other-account-token"},
    )

    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "wrong_account"}
    assert entry.data[CONF_TOKEN] == "old-token"


async def test_reconfigure_updates_scope_and_drops_stale_options(
    hass: HomeAssistant,
    mock_groupalarm: dict[str, AsyncMock],
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_SCAN_INTERVAL: 75,
            CONF_ORGANIZATION_DURATIONS: {"7": 10},
            CONF_FEEDBACK_DEVICE_ID: 91,
        },
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
            "unique_id": entry.unique_id,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_TOKEN: "new-token"},
    )
    assert result["step_id"] == "reconfigure_organizations"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_ORGANIZATION_IDS: ["12"]},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_TOKEN] == "new-token"
    assert entry.data[CONF_ORGANIZATION_IDS] == [12]
    assert entry.data[CONF_ORGANIZATION_NAMES] == {"12": "Bravo"}
    assert entry.options == {
        CONF_SCAN_INTERVAL: 75,
        CONF_ORGANIZATION_DURATIONS: {},
    }
    assert entry.unique_id == "user_41_organizations_12"


async def test_options_update_scope_interval_and_reload(
    hass: HomeAssistant,
    mock_groupalarm: dict[str, AsyncMock],
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    with patch.object(
        hass.config_entries,
        "async_schedule_reload",
        wraps=hass.config_entries.async_schedule_reload,
    ) as schedule_reload:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["step_id"] == "init"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_ORGANIZATION_IDS: ["12"],
                CONF_SCAN_INTERVAL: 90,
            },
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_ORGANIZATION_IDS] == [12]
    assert entry.options == {
        CONF_SCAN_INTERVAL: 90,
        CONF_ORGANIZATION_DURATIONS: {},
    }
    assert entry.unique_id == "user_41_organizations_12"
    schedule_reload.assert_called_once_with(entry.entry_id)
