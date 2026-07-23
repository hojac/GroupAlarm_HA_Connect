from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GroupAlarmApiClient
from .const import (
    CONF_ORG_ID,
    CONF_ORG_DURATIONS,
    CONF_ORG_IDS,
    CONF_ORG_NAMES,
    CONF_PAT,
    CONF_SCAN_INTERVAL,
    CONF_FEEDBACK_DEVICE_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import GroupAlarmCoordinator


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry so changed organizations and arrival times take effect."""
    await hass.config_entries.async_reload(entry.entry_id)


def _entry_organization_ids(entry: ConfigEntry) -> list[int]:
    if CONF_ORG_IDS in entry.data:
        return [int(org_id) for org_id in entry.data[CONF_ORG_IDS]]
    return [int(entry.data[CONF_ORG_ID])]


def _entry_organization_name(entry: ConfigEntry, org_id: int) -> str:
    names = entry.data.get(CONF_ORG_NAMES, {})
    return str(names.get(str(org_id), names.get(org_id, org_id)))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    session = async_get_clientsession(hass)
    api = GroupAlarmApiClient(session, entry.data[CONF_PAT])
    scan_interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    durations = entry.options.get(CONF_ORG_DURATIONS, {})
    device_id = entry.options.get(CONF_FEEDBACK_DEVICE_ID)

    coordinators: dict[int, GroupAlarmCoordinator] = {}
    for org_id in _entry_organization_ids(entry):
        coordinator = GroupAlarmCoordinator(
            hass,
            api,
            org_id,
            _entry_organization_name(entry, org_id),
            scan_interval,
            arrival_duration=durations.get(str(org_id), durations.get(org_id)),
            feedback_device_id=device_id,
        )
        await coordinator.async_config_entry_first_refresh()
        coordinators[org_id] = coordinator

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinators
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
