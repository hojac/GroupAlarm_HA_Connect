"""GroupAlarm HA Connect integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    GroupAlarmAuthenticationError,
    GroupAlarmClient,
    GroupAlarmError,
    GroupAlarmPermissionError,
)
from .const import (
    CONF_FEEDBACK_DEVICE_ID,
    CONF_ORGANIZATION_DURATIONS,
    CONF_ORGANIZATION_IDS,
    CONF_ORGANIZATION_NAMES,
    CONF_SCAN_INTERVAL,
    CONF_USER_ID,
    CONFIG_ENTRY_VERSION,
    DEFAULT_SCAN_INTERVAL,
    LEGACY_CONF_ORGANIZATION_ID,
    LEGACY_CONF_PAT,
    MAX_ARRIVAL_DURATION,
    MAX_SCAN_INTERVAL,
    MIN_ARRIVAL_DURATION,
    MIN_SCAN_INTERVAL,
)
from .models import GroupAlarmConfigEntry, GroupAlarmRuntimeData, build_entry_unique_id


async def async_setup_entry(hass: HomeAssistant, entry: GroupAlarmConfigEntry) -> bool:
    """Set up GroupAlarm HA Connect from a config entry."""
    client = GroupAlarmClient(
        async_get_clientsession(hass),
        token=entry.data[CONF_TOKEN],
    )

    try:
        user = await client.async_get_current_user()
    except (GroupAlarmAuthenticationError, GroupAlarmPermissionError) as err:
        raise ConfigEntryAuthFailed("GroupAlarm credentials were rejected") from err
    except GroupAlarmError as err:
        raise ConfigEntryNotReady("Unable to connect to GroupAlarm") from err

    stored_user_id = entry.data.get(CONF_USER_ID)
    if stored_user_id is not None and stored_user_id != user.id:
        raise ConfigEntryAuthFailed(
            "The GroupAlarm token belongs to a different account"
        )

    organization_ids = tuple(entry.data[CONF_ORGANIZATION_IDS])
    expected_unique_id = build_entry_unique_id(user.id, organization_ids)
    if stored_user_id != user.id or entry.unique_id != expected_unique_id:
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_USER_ID: user.id},
            unique_id=expected_unique_id,
        )

    entry.runtime_data = GroupAlarmRuntimeData(client=client, user=user)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GroupAlarmConfigEntry) -> bool:
    """Unload a GroupAlarm config entry."""
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate legacy config entries to the v0.5 data model."""
    if entry.version > CONFIG_ENTRY_VERSION:
        return False

    if entry.version < CONFIG_ENTRY_VERSION:
        new_data = dict(entry.data)
        new_options = dict(entry.options)

        if CONF_TOKEN not in new_data:
            token = new_data.pop(LEGACY_CONF_PAT, None)
            if not isinstance(token, str) or not token:
                return False
            new_data[CONF_TOKEN] = token
        else:
            new_data.pop(LEGACY_CONF_PAT, None)

        if CONF_ORGANIZATION_IDS not in new_data:
            organization_id = new_data.get(LEGACY_CONF_ORGANIZATION_ID)
            if organization_id is None:
                return False
            new_data[CONF_ORGANIZATION_IDS] = [int(organization_id)]

        try:
            organization_ids = sorted(
                {int(value) for value in new_data[CONF_ORGANIZATION_IDS]}
            )
        except (TypeError, ValueError):
            return False
        if not organization_ids or any(value < 1 for value in organization_ids):
            return False
        new_data[CONF_ORGANIZATION_IDS] = organization_ids
        new_data.pop(LEGACY_CONF_ORGANIZATION_ID, None)

        raw_names = new_data.get(CONF_ORGANIZATION_NAMES, {})
        names = raw_names if isinstance(raw_names, dict) else {}
        new_data[CONF_ORGANIZATION_NAMES] = {
            str(organization_id): str(
                names.get(
                    str(organization_id),
                    names.get(organization_id, organization_id),
                )
            )
            for organization_id in organization_ids
        }

        raw_interval = new_options.get(
            CONF_SCAN_INTERVAL,
            new_data.pop(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        try:
            scan_interval = int(raw_interval)
        except (TypeError, ValueError):
            scan_interval = DEFAULT_SCAN_INTERVAL
        if not MIN_SCAN_INTERVAL <= scan_interval <= MAX_SCAN_INTERVAL:
            scan_interval = DEFAULT_SCAN_INTERVAL

        raw_durations = new_options.get(CONF_ORGANIZATION_DURATIONS, {})
        durations: dict[str, int] = {}
        if isinstance(raw_durations, dict):
            for organization_id, raw_duration in raw_durations.items():
                try:
                    organization_id_int = int(organization_id)
                    duration = int(raw_duration)
                except (TypeError, ValueError):
                    continue
                if (
                    organization_id_int in organization_ids
                    and MIN_ARRIVAL_DURATION <= duration <= MAX_ARRIVAL_DURATION
                ):
                    durations[str(organization_id_int)] = duration

        migrated_options: dict[str, object] = {
            CONF_SCAN_INTERVAL: scan_interval,
            CONF_ORGANIZATION_DURATIONS: durations,
        }
        feedback_device_id = new_options.get(CONF_FEEDBACK_DEVICE_ID)
        if durations and isinstance(feedback_device_id, int):
            migrated_options[CONF_FEEDBACK_DEVICE_ID] = feedback_device_id

        hass.config_entries.async_update_entry(
            entry,
            data=new_data,
            options=migrated_options,
            unique_id=None,
            version=CONFIG_ENTRY_VERSION,
        )

    return True
