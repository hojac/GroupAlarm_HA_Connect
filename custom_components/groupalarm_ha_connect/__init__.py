"""GroupAlarm HA Connect integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    GroupAlarmAuthenticationError,
    GroupAlarmClient,
    GroupAlarmError,
    GroupAlarmOrganization,
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
    DOMAIN,
    LEGACY_CONF_ORGANIZATION_ID,
    LEGACY_CONF_PAT,
    MAX_ARRIVAL_DURATION,
    MAX_SCAN_INTERVAL,
    MIN_ARRIVAL_DURATION,
    MIN_SCAN_INTERVAL,
    PLATFORMS,
)
from .coordinator import GroupAlarmCoordinator
from .models import (
    GroupAlarmConfigEntry,
    GroupAlarmRuntimeData,
    build_device_identifier,
    build_entity_unique_id,
    build_entry_unique_id,
)
from .repairs import async_sync_feedback_device_issue

_LEGACY_ENTITY_KEY_MIGRATIONS = {
    ("sensor", "end"): "feedback_deadline",
    ("sensor", "countdown"): "feedback_countdown",
}
_REMOVED_LEGACY_ENTITY_KEYS = {
    ("sensor", "address"),
    ("sensor", "latitude"),
    ("sensor", "longitude"),
}


def _organization_names(
    entry: GroupAlarmConfigEntry,
    organizations: tuple[GroupAlarmOrganization, ...],
) -> dict[int, str]:
    """Resolve current names while retaining inaccessible configured scopes."""
    current = {organization.id: organization.name for organization in organizations}
    stored = entry.data.get(CONF_ORGANIZATION_NAMES, {})
    stored_names = stored if isinstance(stored, dict) else {}
    return {
        organization_id: current.get(
            organization_id,
            str(
                stored_names.get(
                    str(organization_id),
                    stored_names.get(organization_id, organization_id),
                )
            ),
        )
        for organization_id in sorted(
            {int(value) for value in entry.data[CONF_ORGANIZATION_IDS]}
        )
    }


def _registry_organization_id(
    identifier: str,
    *,
    entry_id: str,
    user_id: int,
) -> tuple[int, str] | None:
    """Parse a legacy or current entity unique ID owned by this entry."""
    legacy_prefix = f"{entry_id}_"
    current_prefix = f"user_{user_id}_organization_"
    if identifier.startswith(legacy_prefix):
        remainder = identifier.removeprefix(legacy_prefix)
    elif identifier.startswith(current_prefix):
        remainder = identifier.removeprefix(current_prefix)
    else:
        return None
    organization, separator, entity_key = remainder.partition("_")
    if not separator or not organization.isdigit() or not entity_key:
        return None
    organization_id = int(organization)
    if organization_id < 1:
        return None
    return organization_id, entity_key


def _migrate_registries(
    hass: HomeAssistant,
    entry: GroupAlarmConfigEntry,
    *,
    user_id: int,
    organization_ids: set[int],
) -> None:
    """Migrate legacy identities and remove stale organization records."""
    entity_registry = er.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(
        entity_registry,
        entry.entry_id,
    ):
        parsed = _registry_organization_id(
            registry_entry.unique_id,
            entry_id=entry.entry_id,
            user_id=user_id,
        )
        if parsed is None:
            continue
        organization_id, entity_key = parsed
        if organization_id not in organization_ids:
            entity_registry.async_remove(registry_entry.entity_id)
            continue
        legacy_identity = (registry_entry.domain, entity_key)
        if legacy_identity in _REMOVED_LEGACY_ENTITY_KEYS:
            entity_registry.async_remove(registry_entry.entity_id)
            continue
        entity_key = _LEGACY_ENTITY_KEY_MIGRATIONS.get(
            legacy_identity,
            entity_key,
        )
        new_unique_id = build_entity_unique_id(
            user_id,
            organization_id,
            entity_key,
        )
        if registry_entry.unique_id == new_unique_id:
            continue
        duplicate = entity_registry.async_get_entity_id(
            registry_entry.domain,
            DOMAIN,
            new_unique_id,
        )
        if duplicate is not None and duplicate != registry_entry.entity_id:
            target_entry = entity_registry.async_get(duplicate)
            if (
                target_entry is not None
                and target_entry.config_entry_id == entry.entry_id
            ):
                aliases = list(target_entry.aliases)
                aliases.extend(
                    alias for alias in registry_entry.aliases if alias not in aliases
                )
                categories = {
                    **registry_entry.categories,
                    **target_entry.categories,
                }
                labels = registry_entry.labels | target_entry.labels
                options = {
                    **registry_entry.options,
                    **target_entry.options,
                }
                canonical_entity_id = registry_entry.entity_id
                entity_registry.async_remove(canonical_entity_id)
                merged_entry = entity_registry.async_update_entity(
                    target_entry.entity_id,
                    aliases=aliases,
                    area_id=(
                        target_entry.area_id
                        if target_entry.area_id is not None
                        else registry_entry.area_id
                    ),
                    categories=categories,
                    device_class=(
                        target_entry.device_class
                        if target_entry.device_class is not None
                        else registry_entry.device_class
                    ),
                    disabled_by=(
                        target_entry.disabled_by
                        if target_entry.disabled_by is not None
                        else registry_entry.disabled_by
                    ),
                    hidden_by=(
                        target_entry.hidden_by
                        if target_entry.hidden_by is not None
                        else registry_entry.hidden_by
                    ),
                    icon=(
                        target_entry.icon
                        if target_entry.icon is not None
                        else registry_entry.icon
                    ),
                    labels=labels,
                    name=(
                        target_entry.name
                        if target_entry.name is not None
                        else registry_entry.name
                    ),
                    new_entity_id=canonical_entity_id,
                )
                for option_domain, domain_options in options.items():
                    if merged_entry.options.get(option_domain) != domain_options:
                        merged_entry = entity_registry.async_update_entity_options(
                            merged_entry.entity_id,
                            option_domain,
                            domain_options,
                        )
            else:
                entity_registry.async_remove(registry_entry.entity_id)
            continue
        entity_registry.async_update_entity(
            registry_entry.entity_id,
            new_unique_id=new_unique_id,
        )

    device_registry = dr.async_get(hass)
    current_device_prefix = f"user_{user_id}_organization_"
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        device_organization_id: int | None = None
        for domain, identifier in device.identifiers:
            if domain != DOMAIN:
                continue
            if identifier.isdigit():
                device_organization_id = int(identifier)
            elif identifier.startswith(current_device_prefix):
                raw_id = identifier.removeprefix(current_device_prefix)
                if raw_id.isdigit():
                    device_organization_id = int(raw_id)
            if device_organization_id is not None:
                break
        if device_organization_id is None:
            continue
        if device_organization_id not in organization_ids:
            device_registry.async_update_device(
                device.id,
                remove_config_entry_id=entry.entry_id,
            )
            continue
        device_registry.async_update_device(
            device.id,
            new_identifiers={
                (
                    DOMAIN,
                    build_device_identifier(user_id, device_organization_id),
                )
            },
        )


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

    try:
        organizations = await client.async_get_organizations()
    except (GroupAlarmAuthenticationError, GroupAlarmPermissionError) as err:
        raise ConfigEntryAuthFailed("GroupAlarm credentials were rejected") from err
    except GroupAlarmError as err:
        raise ConfigEntryNotReady("Unable to connect to GroupAlarm") from err

    organization_ids = tuple(
        sorted({int(value) for value in entry.data[CONF_ORGANIZATION_IDS]})
    )
    expected_unique_id = build_entry_unique_id(user.id, organization_ids)
    names = _organization_names(entry, organizations)
    serialized_names = {
        str(organization_id): name for organization_id, name in names.items()
    }
    if (
        stored_user_id != user.id
        or entry.unique_id != expected_unique_id
        or entry.data.get(CONF_ORGANIZATION_NAMES) != serialized_names
    ):
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_USER_ID: user.id,
                CONF_ORGANIZATION_NAMES: serialized_names,
            },
            unique_id=expected_unique_id,
        )

    scan_interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    coordinator = GroupAlarmCoordinator(
        hass,
        entry,
        client,
        user,
        names,
        scan_interval,
    )
    await coordinator.async_config_entry_first_refresh()
    async_sync_feedback_device_issue(hass, entry)

    _migrate_registries(
        hass,
        entry,
        user_id=user.id,
        organization_ids=set(organization_ids),
    )
    entry.runtime_data = GroupAlarmRuntimeData(
        client=client,
        user=user,
        coordinator=coordinator,
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GroupAlarmConfigEntry) -> bool:
    """Unload a GroupAlarm config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.coordinator.async_shutdown()
    return unloaded


async def _async_reload_entry(
    hass: HomeAssistant,
    entry: GroupAlarmConfigEntry,
) -> None:
    """Reload after an external config-entry update."""
    await hass.config_entries.async_reload(entry.entry_id)


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
