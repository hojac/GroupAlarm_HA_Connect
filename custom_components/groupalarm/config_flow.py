from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GroupAlarmApiClient, GroupAlarmApiError
from .const import (
    CONF_ORG_IDS,
    CONF_ORG_NAMES,
    CONF_PAT,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)


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


class GroupAlarmConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self._token: str | None = None
        self._scan_interval: int = DEFAULT_SCAN_INTERVAL
        self._organizations: list[dict[str, Any]] = []
        self._user_id: int | None = None

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
                await self.async_set_unique_id(f"user_{self._user_id}")
                self._abort_if_unique_id_configured()
                selected_names = {org_id: names.get(org_id, org_id) for org_id in selected}
                title = "GroupAlarm"
                if len(selected) == 1:
                    title = f"GroupAlarm {selected_names[selected[0]]}"
                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_PAT: self._token,
                        CONF_ORG_IDS: [int(org_id) for org_id in selected],
                        CONF_ORG_NAMES: selected_names,
                    },
                    options={CONF_SCAN_INTERVAL: self._scan_interval},
                )

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

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return GroupAlarmOptionsFlow(config_entry)


class GroupAlarmOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry
        self._organizations: list[dict[str, Any]] = []

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
                selected_names = {org_id: names.get(org_id, org_id) for org_id in selected}
                self.hass.config_entries.async_update_entry(
                    self._entry,
                    data={
                        **self._entry.data,
                        CONF_ORG_IDS: [int(org_id) for org_id in selected],
                        CONF_ORG_NAMES: selected_names,
                    },
                )
                return self.async_create_entry(
                    title="",
                    data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])},
                )

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
