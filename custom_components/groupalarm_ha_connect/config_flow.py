"""Config, reauthentication, reconfigure and options flows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    GroupAlarmAuthenticationError,
    GroupAlarmClient,
    GroupAlarmError,
    GroupAlarmOrganization,
    GroupAlarmPermissionError,
    GroupAlarmRequestError,
    GroupAlarmResponseError,
    GroupAlarmUser,
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
)
from .models import build_entry_unique_id

CONF_ARRIVAL_DURATION = "arrival_duration"


def _token_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_TOKEN): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            )
        }
    )


def _user_schema(default_scan_interval: int) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_TOKEN): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Required(
                CONF_SCAN_INTERVAL, default=default_scan_interval
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="s",
                )
            ),
        }
    )


def _organization_schema(
    organizations: tuple[GroupAlarmOrganization, ...],
    *,
    default: list[str],
    include_scan_interval: int | None = None,
) -> vol.Schema:
    fields: dict[vol.Marker, object] = {
        vol.Required(CONF_ORGANIZATION_IDS, default=default): SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(
                        value=str(organization.id),
                        label=organization.name,
                    )
                    for organization in organizations
                ],
                multiple=True,
                mode=SelectSelectorMode.LIST,
            )
        )
    }
    if include_scan_interval is not None:
        fields[vol.Required(CONF_SCAN_INTERVAL, default=include_scan_interval)] = (
            NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="s",
                )
            )
        )
    return vol.Schema(fields)


def _arrival_duration_schema(current: int | None) -> vol.Schema:
    marker: vol.Marker
    if current is None:
        marker = vol.Optional(CONF_ARRIVAL_DURATION)
    else:
        marker = vol.Optional(CONF_ARRIVAL_DURATION, default=current)
    return vol.Schema(
        {
            marker: NumberSelector(
                NumberSelectorConfig(
                    min=MIN_ARRIVAL_DURATION,
                    max=MAX_ARRIVAL_DURATION,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="min",
                )
            )
        }
    )


def _entry_token(entry: ConfigEntry) -> str:
    token = entry.data.get(CONF_TOKEN, entry.data.get(LEGACY_CONF_PAT))
    if not isinstance(token, str) or not token:
        raise ValueError("Config entry does not contain a token")
    return token


def _entry_organization_ids(entry: ConfigEntry) -> set[int]:
    values = entry.data.get(CONF_ORGANIZATION_IDS)
    if values is None:
        legacy = entry.data.get(LEGACY_CONF_ORGANIZATION_ID)
        return {int(legacy)} if legacy is not None else set()
    return {int(value) for value in values}


def _entry_uses_account(
    entry: ConfigEntry,
    *,
    user_id: int,
    token: str | None,
) -> bool:
    entry_user_id = entry.data.get(CONF_USER_ID)
    if entry_user_id is not None:
        return int(entry_user_id) == user_id
    if token is None:
        return False
    try:
        return _entry_token(entry) == token
    except ValueError:
        return False


def _has_scope_overlap(
    entries: list[ConfigEntry],
    *,
    user_id: int,
    organization_ids: set[int],
    token: str | None,
    exclude_entry_id: str | None = None,
) -> bool:
    return any(
        entry.entry_id != exclude_entry_id
        and _entry_uses_account(entry, user_id=user_id, token=token)
        and bool(_entry_organization_ids(entry) & organization_ids)
        for entry in entries
    )


def _organization_names(
    organizations: tuple[GroupAlarmOrganization, ...],
    selected_ids: set[int],
) -> dict[str, str]:
    return {
        str(organization.id): organization.name
        for organization in organizations
        if organization.id in selected_ids
    }


def _entry_title(names: Mapping[str, str]) -> str:
    if len(names) == 1:
        return f"GroupAlarm HA Connect {next(iter(names.values()))}"
    return "GroupAlarm HA Connect"


def _filtered_options(
    options: Mapping[str, Any], selected_ids: set[int]
) -> dict[str, Any]:
    result = dict(options)
    durations = {
        str(organization_id): int(duration)
        for organization_id, duration in result.get(
            CONF_ORGANIZATION_DURATIONS, {}
        ).items()
        if int(organization_id) in selected_ids
    }
    result[CONF_ORGANIZATION_DURATIONS] = durations
    if not durations:
        result.pop(CONF_FEEDBACK_DEVICE_ID, None)
    return result


async def _async_validate_account(
    hass: HomeAssistant, token: str
) -> tuple[
    GroupAlarmUser | None,
    tuple[GroupAlarmOrganization, ...],
    str | None,
]:
    client = GroupAlarmClient(async_get_clientsession(hass), token=token)
    try:
        user = await client.async_get_current_user()
        organizations = await client.async_get_organizations()
    except (GroupAlarmAuthenticationError, GroupAlarmPermissionError):
        return None, (), "invalid_auth"
    except GroupAlarmRequestError as err:
        if err.status == 422:
            return None, (), "invalid_auth"
        return None, (), "invalid_response"
    except GroupAlarmResponseError:
        return None, (), "invalid_response"
    except GroupAlarmError:
        return None, (), "cannot_connect"
    if not organizations:
        return user, (), "no_organizations"
    return user, organizations, None


class GroupAlarmConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle GroupAlarm HA Connect configuration."""

    VERSION = CONFIG_ENTRY_VERSION

    def __init__(self) -> None:
        """Initialize flow state."""
        self._token = ""
        self._scan_interval = DEFAULT_SCAN_INTERVAL
        self._user: GroupAlarmUser | None = None
        self._organizations: tuple[GroupAlarmOrganization, ...] = ()
        self._selected_ids: list[int] = []
        self._selected_names: dict[str, str] = {}
        self._durations: dict[str, int] = {}
        self._duration_index = 0

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate credentials and load account metadata."""
        errors: dict[str, str] = {}
        if user_input is not None:
            token = str(user_input[CONF_TOKEN]).strip()
            user, organizations, error = await _async_validate_account(self.hass, token)
            if error is not None:
                errors["base"] = error
            else:
                assert user is not None
                self._token = token
                self._scan_interval = int(user_input[CONF_SCAN_INTERVAL])
                self._user = user
                self._organizations = organizations
                return await self.async_step_organizations()

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(DEFAULT_SCAN_INTERVAL),
            errors=errors,
        )

    async def async_step_organizations(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select the organization scope."""
        errors: dict[str, str] = {}
        available_ids = {organization.id for organization in self._organizations}
        if user_input is not None:
            selected_ids = {int(value) for value in user_input[CONF_ORGANIZATION_IDS]}
            if not selected_ids:
                errors["base"] = "no_organizations_selected"
            elif not selected_ids <= available_ids:
                errors["base"] = "invalid_organization"
            else:
                assert self._user is not None
                if _has_scope_overlap(
                    self._async_current_entries(),
                    user_id=self._user.id,
                    organization_ids=selected_ids,
                    token=self._token,
                ):
                    errors["base"] = "organization_already_configured"
                else:
                    self._selected_ids = sorted(selected_ids)
                    self._selected_names = _organization_names(
                        self._organizations, selected_ids
                    )
                    self._duration_index = 0
                    return await self.async_step_arrival_times()

        return self.async_show_form(
            step_id="organizations",
            data_schema=_organization_schema(
                self._organizations,
                default=[str(organization.id) for organization in self._organizations],
            ),
            errors=errors,
        )

    async def async_step_arrival_times(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure an optional arrival duration per organization."""
        organization_id = self._selected_ids[self._duration_index]
        organization_key = str(organization_id)
        if user_input is not None:
            raw_duration = user_input.get(CONF_ARRIVAL_DURATION)
            if raw_duration in (None, ""):
                self._durations.pop(organization_key, None)
            else:
                assert isinstance(raw_duration, str | int | float)
                assert not isinstance(raw_duration, bool)
                self._durations[organization_key] = int(raw_duration)
            self._duration_index += 1
            if self._duration_index < len(self._selected_ids):
                return await self.async_step_arrival_times()
            if self._durations:
                return await self.async_step_feedback_device()
            return await self._async_create_entry()

        return self.async_show_form(
            step_id="arrival_times",
            data_schema=_arrival_duration_schema(self._durations.get(organization_key)),
            description_placeholders={
                "organization": self._selected_names[organization_key]
            },
        )

    async def async_step_feedback_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Require an explicit active app device for timed feedback."""
        assert self._user is not None
        client = GroupAlarmClient(async_get_clientsession(self.hass), token=self._token)
        errors: dict[str, str] = {}
        try:
            devices = await client.async_get_app_devices(self._user.id)
        except (GroupAlarmAuthenticationError, GroupAlarmPermissionError):
            devices = ()
            errors["base"] = "invalid_auth"
        except GroupAlarmResponseError:
            devices = ()
            errors["base"] = "invalid_response"
        except GroupAlarmError:
            devices = ()
            errors["base"] = "cannot_load_devices"

        active_devices = tuple(device for device in devices if device.active)
        if user_input is not None and active_devices:
            selected_device_id = int(user_input[CONF_FEEDBACK_DEVICE_ID])
            if selected_device_id not in {device.id for device in active_devices}:
                errors["base"] = "invalid_device"
            else:
                return await self._async_create_entry(selected_device_id)
        if not active_devices and not errors:
            errors["base"] = "no_active_devices"

        return self.async_show_form(
            step_id="feedback_device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_FEEDBACK_DEVICE_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(
                                    value=str(device.id),
                                    label=device.name,
                                )
                                for device in active_devices
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def _async_create_entry(
        self, feedback_device_id: int | None = None
    ) -> ConfigFlowResult:
        assert self._user is not None
        unique_id = build_entry_unique_id(self._user.id, tuple(self._selected_ids))
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        options: dict[str, Any] = {
            CONF_SCAN_INTERVAL: self._scan_interval,
            CONF_ORGANIZATION_DURATIONS: dict(self._durations),
        }
        if feedback_device_id is not None:
            options[CONF_FEEDBACK_DEVICE_ID] = feedback_device_id

        return self.async_create_entry(
            title=_entry_title(self._selected_names),
            data={
                CONF_TOKEN: self._token,
                CONF_USER_ID: self._user.id,
                CONF_ORGANIZATION_IDS: self._selected_ids,
                CONF_ORGANIZATION_NAMES: self._selected_names,
            },
            options=options,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate and store a replacement token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            token = str(user_input[CONF_TOKEN]).strip()
            user, _organizations, error = await _async_validate_account(
                self.hass, token
            )
            entry = self._get_reauth_entry()
            expected_user_id = entry.data.get(CONF_USER_ID)
            if error is not None:
                errors["base"] = error
            elif expected_user_id is not None and (
                user is None or user.id != int(expected_user_id)
            ):
                errors["base"] = "wrong_account"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_TOKEN: token},
                    reason="reauth_successful",
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_token_schema(),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate credentials before reconfiguring the account scope."""
        errors: dict[str, str] = {}
        if user_input is not None:
            token = str(user_input[CONF_TOKEN]).strip()
            user, organizations, error = await _async_validate_account(self.hass, token)
            entry = self._get_reconfigure_entry()
            expected_user_id = entry.data.get(CONF_USER_ID)
            if error is not None:
                errors["base"] = error
            elif expected_user_id is not None and (
                user is None or user.id != int(expected_user_id)
            ):
                errors["base"] = "wrong_account"
            else:
                assert user is not None
                self._token = token
                self._user = user
                self._organizations = organizations
                return await self.async_step_reconfigure_organizations()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_token_schema(),
            errors=errors,
        )

    async def async_step_reconfigure_organizations(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update credentials and organization scope."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        available_ids = {organization.id for organization in self._organizations}
        if user_input is not None:
            selected_ids = {int(value) for value in user_input[CONF_ORGANIZATION_IDS]}
            if not selected_ids:
                errors["base"] = "no_organizations_selected"
            elif not selected_ids <= available_ids:
                errors["base"] = "invalid_organization"
            else:
                assert self._user is not None
                if _has_scope_overlap(
                    self._async_current_entries(),
                    user_id=self._user.id,
                    organization_ids=selected_ids,
                    token=self._token,
                    exclude_entry_id=entry.entry_id,
                ):
                    errors["base"] = "organization_already_configured"
                else:
                    names = _organization_names(self._organizations, selected_ids)
                    data = {
                        CONF_TOKEN: self._token,
                        CONF_USER_ID: self._user.id,
                        CONF_ORGANIZATION_IDS: sorted(selected_ids),
                        CONF_ORGANIZATION_NAMES: names,
                    }
                    return self.async_update_reload_and_abort(
                        entry,
                        unique_id=build_entry_unique_id(
                            self._user.id, tuple(selected_ids)
                        ),
                        title=_entry_title(names),
                        data=data,
                        options=_filtered_options(entry.options, selected_ids),
                    )

        return self.async_show_form(
            step_id="reconfigure_organizations",
            data_schema=_organization_schema(
                self._organizations,
                default=[
                    str(value) for value in sorted(_entry_organization_ids(entry))
                ],
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> GroupAlarmOptionsFlow:
        """Return the options flow."""
        return GroupAlarmOptionsFlow()


class GroupAlarmOptionsFlow(OptionsFlowWithReload):
    """Configure polling, scope and optional arrival durations."""

    def __init__(self) -> None:
        """Initialize options flow state."""
        self._organizations: tuple[GroupAlarmOrganization, ...] = ()
        self._selected_ids: list[int] = []
        self._selected_names: dict[str, str] = {}
        self._scan_interval = DEFAULT_SCAN_INTERVAL
        self._durations: dict[str, int] = {}
        self._duration_index = 0

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select organizations and the polling interval."""
        errors: dict[str, str] = {}
        try:
            token = _entry_token(self.config_entry)
        except ValueError:
            return self.async_abort(reason="invalid_auth")

        client = GroupAlarmClient(async_get_clientsession(self.hass), token=token)
        if not self._organizations:
            try:
                self._organizations = await client.async_get_organizations()
            except (GroupAlarmAuthenticationError, GroupAlarmPermissionError):
                errors["base"] = "invalid_auth"
            except GroupAlarmResponseError:
                errors["base"] = "invalid_response"
            except GroupAlarmError:
                errors["base"] = "cannot_connect"

        current_ids = _entry_organization_ids(self.config_entry)
        current_interval = int(
            self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        available_ids = {organization.id for organization in self._organizations}

        if user_input is not None and not errors:
            selected_ids = {int(value) for value in user_input[CONF_ORGANIZATION_IDS]}
            if not selected_ids:
                errors["base"] = "no_organizations_selected"
            elif not selected_ids <= available_ids:
                errors["base"] = "invalid_organization"
            else:
                user_id = int(self.config_entry.data[CONF_USER_ID])
                if _has_scope_overlap(
                    self.hass.config_entries.async_entries(DOMAIN),
                    user_id=user_id,
                    organization_ids=selected_ids,
                    token=token,
                    exclude_entry_id=self.config_entry.entry_id,
                ):
                    errors["base"] = "organization_already_configured"
                else:
                    self._selected_ids = sorted(selected_ids)
                    self._selected_names = _organization_names(
                        self._organizations, selected_ids
                    )
                    self._scan_interval = int(user_input[CONF_SCAN_INTERVAL])
                    self._durations = {
                        str(organization_id): int(duration)
                        for organization_id, duration in self.config_entry.options.get(
                            CONF_ORGANIZATION_DURATIONS, {}
                        ).items()
                        if int(organization_id) in selected_ids
                    }
                    self._duration_index = 0
                    return await self.async_step_arrival_times()

        return self.async_show_form(
            step_id="init",
            data_schema=_organization_schema(
                self._organizations,
                default=[str(value) for value in sorted(current_ids)],
                include_scan_interval=current_interval,
            ),
            errors=errors,
        )

    async def async_step_arrival_times(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure an optional arrival duration per organization."""
        organization_id = self._selected_ids[self._duration_index]
        organization_key = str(organization_id)
        if user_input is not None:
            raw_duration = user_input.get(CONF_ARRIVAL_DURATION)
            if raw_duration in (None, ""):
                self._durations.pop(organization_key, None)
            else:
                assert isinstance(raw_duration, str | int | float)
                assert not isinstance(raw_duration, bool)
                self._durations[organization_key] = int(raw_duration)
            self._duration_index += 1
            if self._duration_index < len(self._selected_ids):
                return await self.async_step_arrival_times()
            if self._durations:
                return await self.async_step_feedback_device()
            return self._save(None)

        return self.async_show_form(
            step_id="arrival_times",
            data_schema=_arrival_duration_schema(self._durations.get(organization_key)),
            description_placeholders={
                "organization": self._selected_names[organization_key]
            },
        )

    async def async_step_feedback_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select an active app device for timed feedback."""
        token = _entry_token(self.config_entry)
        user_id = int(self.config_entry.data[CONF_USER_ID])
        client = GroupAlarmClient(async_get_clientsession(self.hass), token=token)
        errors: dict[str, str] = {}
        try:
            devices = await client.async_get_app_devices(user_id)
        except (GroupAlarmAuthenticationError, GroupAlarmPermissionError):
            devices = ()
            errors["base"] = "invalid_auth"
        except GroupAlarmResponseError:
            devices = ()
            errors["base"] = "invalid_response"
        except GroupAlarmError:
            devices = ()
            errors["base"] = "cannot_load_devices"

        active_devices = tuple(device for device in devices if device.active)
        if user_input is not None and active_devices:
            selected_device_id = int(user_input[CONF_FEEDBACK_DEVICE_ID])
            if selected_device_id not in {device.id for device in active_devices}:
                errors["base"] = "invalid_device"
            else:
                return self._save(selected_device_id)
        if not active_devices and not errors:
            errors["base"] = "no_active_devices"

        current_device_id = self.config_entry.options.get(CONF_FEEDBACK_DEVICE_ID)
        active_ids = {device.id for device in active_devices}
        marker: vol.Marker
        if current_device_id in active_ids:
            marker = vol.Required(
                CONF_FEEDBACK_DEVICE_ID, default=str(current_device_id)
            )
        else:
            marker = vol.Required(CONF_FEEDBACK_DEVICE_ID)

        return self.async_show_form(
            step_id="feedback_device",
            data_schema=vol.Schema(
                {
                    marker: SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(
                                    value=str(device.id),
                                    label=device.name,
                                )
                                for device in active_devices
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
            errors=errors,
        )

    def _save(self, feedback_device_id: int | None) -> ConfigFlowResult:
        """Persist data and options, then let HA reload the entry."""
        user_id = int(self.config_entry.data[CONF_USER_ID])
        selected_set = set(self._selected_ids)
        data = {
            **self.config_entry.data,
            CONF_ORGANIZATION_IDS: self._selected_ids,
            CONF_ORGANIZATION_NAMES: self._selected_names,
        }
        data.pop(LEGACY_CONF_ORGANIZATION_ID, None)
        options: dict[str, Any] = {
            CONF_SCAN_INTERVAL: self._scan_interval,
            CONF_ORGANIZATION_DURATIONS: {
                key: value
                for key, value in self._durations.items()
                if int(key) in selected_set
            },
        }
        if feedback_device_id is not None:
            options[CONF_FEEDBACK_DEVICE_ID] = feedback_device_id

        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data=data,
            unique_id=build_entry_unique_id(user_id, tuple(self._selected_ids)),
            title=_entry_title(self._selected_names),
        )
        return self.async_create_entry(
            title=self.config_entry.title,
            data=options,
        )
