from __future__ import annotations

from typing import Any
import hashlib

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GroupAlarmApiClient, GroupAlarmApiError
from .const import (
    CONF_ORG_IDS,
    CONF_ORG_NAMES,
    CONF_ORG_DURATIONS,
    CONF_PAT,
    CONF_SCAN_INTERVAL,
    CONF_FEEDBACK_DEVICE_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_ARRIVAL_DURATION,
)

CONF_ARRIVAL_DURATION = "arrival_duration"


def _org_id(org: dict[str, Any]) -> int | None:
    for key in ("id", "organizationID", "organizationId"):
        value = org.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    return None


def _org_name(org: dict[str, Any], org_id: int) -> str:
    for key in ("name", "organizationName", "displayName"):
        value = org.get(key)
        if value:
            return str(value)
    return str(org_id)


def _org_options(organizations: list[dict[str, Any]]) -> tuple[list[selector.SelectOptionDict], dict[str, str]]:
    options: list[selector.SelectOptionDict] = []
    names: dict[str, str] = {}
    for org in organizations:
        oid = _org_id(org)
        if oid is None:
            continue
        name = _org_name(org, oid)
        oid_str = str(oid)
        names[oid_str] = name
        options.append(selector.SelectOptionDict(value=oid_str, label=name))
    return options, names


def _duration_schema(current: int | None = None) -> vol.Schema:
    field = (
        vol.Optional(CONF_ARRIVAL_DURATION, default=current)
        if current is not None
        else vol.Optional(CONF_ARRIVAL_DURATION)
    )
    return vol.Schema(
        {
            field: selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=MAX_ARRIVAL_DURATION,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="min",
                )
            )
        }
    )


def _device_options(devices: list[dict[str, Any]]) -> list[selector.SelectOptionDict]:
    return [
        selector.SelectOptionDict(
            value=str(device["id"]),
            label=f"{device.get('name') or 'Unbenanntes Gerät'} (ID {device['id']})",
        )
        for device in devices
        if device.get("id") is not None and device.get("active") is True
    ]


class GroupAlarmConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self._token: str | None = None
        self._scan_interval: int = DEFAULT_SCAN_INTERVAL
        self._organizations: list[dict[str, Any]] = []
        self._user_id: int | None = None
        self._selected: list[str] = []
        self._selected_names: dict[str, str] = {}
        self._durations: dict[str, int] = {}
        self._duration_index = 0

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            api = GroupAlarmApiClient(session, user_input[CONF_PAT])
            try:
                user = await api.get_current_user()
                organizations = await api.get_organizations()
            except GroupAlarmApiError:
                errors["base"] = "cannot_connect"
            else:
                options, _names = _org_options(organizations)
                if not options:
                    errors["base"] = "no_organizations"
                else:
                    self._token = user_input[CONF_PAT]
                    self._scan_interval = int(user_input[CONF_SCAN_INTERVAL])
                    self._organizations = organizations
                    self._user_id = int(user.get("id", 0) or 0)
                    return await self.async_step_organizations()

        schema = vol.Schema(
            {
                vol.Required(CONF_PAT): str,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_organizations(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        options, names = _org_options(self._organizations)
        default = [option["value"] for option in options]

        if user_input is not None:
            selected = [str(org_id) for org_id in user_input[CONF_ORG_IDS]]
            if not selected:
                errors["base"] = "no_organizations_selected"
            else:
                self._selected = selected
                self._selected_names = {
                    org_id: names.get(org_id, org_id) for org_id in selected
                }
                return await self.async_step_arrival_times()

        schema = vol.Schema(
            {
                vol.Required(CONF_ORG_IDS, default=default): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(step_id="organizations", data_schema=schema, errors=errors)

    async def async_step_arrival_times(self, user_input: dict[str, Any] | None = None):
        org_id = self._selected[self._duration_index]
        if user_input is not None:
            value = user_input.get(CONF_ARRIVAL_DURATION)
            if value in (None, ""):
                self._durations.pop(org_id, None)
            else:
                self._durations[org_id] = int(value)
            self._duration_index += 1
            if self._duration_index < len(self._selected):
                return await self.async_step_arrival_times()
            if self._durations:
                return await self.async_step_feedback_device()
            return await self._async_create_config_entry()
        return self.async_show_form(
            step_id="arrival_times",
            data_schema=_duration_schema(self._durations.get(org_id)),
            description_placeholders={"organization": self._selected_names[org_id]},
        )

    async def async_step_feedback_device(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        api = GroupAlarmApiClient(
            async_get_clientsession(self.hass), self._token or ""
        )
        try:
            device_options = _device_options(
                await api.get_devices(int(self._user_id or 0))
            )
        except GroupAlarmApiError:
            device_options = []
            errors["base"] = "cannot_load_devices"
        if user_input is not None and device_options:
            return await self._async_create_config_entry(
                int(user_input[CONF_FEEDBACK_DEVICE_ID])
            )
        if not device_options and not errors:
            errors["base"] = "no_active_devices"
        schema = vol.Schema(
            {
                vol.Required(CONF_FEEDBACK_DEVICE_ID): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=device_options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="feedback_device", data_schema=schema, errors=errors
        )

    async def _async_create_config_entry(self, device_id: int | None = None):
        token_hash = hashlib.sha1((self._token or "").encode()).hexdigest()[:12]
        org_key = "_".join(sorted(self._selected))
        await self.async_set_unique_id(
            f"user_{self._user_id}_token_{token_hash}_orgs_{org_key}"
        )
        self._abort_if_unique_id_configured()
        title = "GroupAlarm HA Connect"
        if len(self._selected) == 1:
            title = f"GroupAlarm HA Connect {self._selected_names[self._selected[0]]}"
        options: dict[str, Any] = {
            CONF_SCAN_INTERVAL: self._scan_interval,
            CONF_ORG_DURATIONS: self._durations,
        }
        if device_id is not None:
            options[CONF_FEEDBACK_DEVICE_ID] = device_id
        return self.async_create_entry(
            title=title,
            data={
                CONF_PAT: self._token,
                CONF_ORG_IDS: [int(org_id) for org_id in self._selected],
                CONF_ORG_NAMES: self._selected_names,
            },
            options=options,
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return GroupAlarmOptionsFlow(config_entry)


class GroupAlarmOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry
        self._organizations: list[dict[str, Any]] = []
        self._selected: list[str] = []
        self._selected_names: dict[str, str] = {}
        self._scan_interval = int(
            entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        self._durations: dict[str, int] = {
            str(key): int(value)
            for key, value in entry.options.get(CONF_ORG_DURATIONS, {}).items()
        }
        self._duration_index = 0

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        session = async_get_clientsession(self.hass)
        api = GroupAlarmApiClient(session, self._entry.data[CONF_PAT])
        try:
            self._organizations = await api.get_organizations()
        except GroupAlarmApiError:
            self._organizations = []
            errors["base"] = "cannot_connect"

        options, names = _org_options(self._organizations)
        current_orgs = [str(org_id) for org_id in self._entry.data.get(CONF_ORG_IDS, [])]
        if not current_orgs and "organization_id" in self._entry.data:
            current_orgs = [str(self._entry.data["organization_id"])]
        if not current_orgs:
            current_orgs = [option["value"] for option in options]

        if user_input is not None:
            selected = [str(org_id) for org_id in user_input[CONF_ORG_IDS]]
            if not selected:
                errors["base"] = "no_organizations_selected"
            else:
                self._selected = selected
                self._selected_names = {
                    org_id: names.get(org_id, org_id) for org_id in selected
                }
                self._scan_interval = int(user_input[CONF_SCAN_INTERVAL])
                return await self.async_step_arrival_times()

        schema = vol.Schema(
            {
                vol.Required(CONF_ORG_IDS, default=current_orgs): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=int(self._entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
                ): int,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

    async def async_step_arrival_times(self, user_input: dict[str, Any] | None = None):
        org_id = self._selected[self._duration_index]
        if user_input is not None:
            value = user_input.get(CONF_ARRIVAL_DURATION)
            if value in (None, ""):
                self._durations.pop(org_id, None)
            else:
                self._durations[org_id] = int(value)
            self._duration_index += 1
            if self._duration_index < len(self._selected):
                return await self.async_step_arrival_times()
            self._durations = {
                key: value
                for key, value in self._durations.items()
                if key in self._selected
            }
            if self._durations:
                return await self.async_step_feedback_device()
            return self._save_options(None)
        return self.async_show_form(
            step_id="arrival_times",
            data_schema=_duration_schema(self._durations.get(org_id)),
            description_placeholders={"organization": self._selected_names[org_id]},
        )

    async def async_step_feedback_device(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        api = GroupAlarmApiClient(
            async_get_clientsession(self.hass), self._entry.data[CONF_PAT]
        )
        try:
            user = await api.get_current_user()
            device_options = _device_options(
                await api.get_devices(int(user.get("id", 0) or 0))
            )
        except GroupAlarmApiError:
            device_options = []
            errors["base"] = "cannot_load_devices"
        current_device = self._entry.options.get(CONF_FEEDBACK_DEVICE_ID)
        if user_input is not None and device_options:
            return self._save_options(int(user_input[CONF_FEEDBACK_DEVICE_ID]))
        if not device_options and not errors:
            errors["base"] = "no_active_devices"
        device_ids = {option["value"] for option in device_options}
        default = str(current_device) if str(current_device) in device_ids else None
        field = (
            vol.Required(CONF_FEEDBACK_DEVICE_ID, default=default)
            if default is not None
            else vol.Required(CONF_FEEDBACK_DEVICE_ID)
        )
        return self.async_show_form(
            step_id="feedback_device",
            data_schema=vol.Schema(
                {
                    field: selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=device_options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
            errors=errors,
        )

    def _save_options(self, device_id: int | None):
        self.hass.config_entries.async_update_entry(
            self._entry,
            data={
                **self._entry.data,
                CONF_ORG_IDS: [int(org_id) for org_id in self._selected],
                CONF_ORG_NAMES: self._selected_names,
            },
        )
        options: dict[str, Any] = {
            CONF_SCAN_INTERVAL: self._scan_interval,
            CONF_ORG_DURATIONS: self._durations,
        }
        if device_id is not None:
            options[CONF_FEEDBACK_DEVICE_ID] = device_id
        return self.async_create_entry(title="", data=options)
