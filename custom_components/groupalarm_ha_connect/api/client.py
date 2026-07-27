"""Asynchronous GroupAlarm HTTP client."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, cast

import aiohttp

from ..const import (
    BASE_URL,
    MAX_ARRIVAL_DURATION,
    REQUEST_TIMEOUT_SECONDS,
)
from .exceptions import (
    GroupAlarmAuthenticationError,
    GroupAlarmError,
    GroupAlarmPermissionError,
    GroupAlarmRateLimitError,
    GroupAlarmRequestError,
    GroupAlarmResponseError,
    GroupAlarmServerError,
    GroupAlarmTimeoutError,
    GroupAlarmTransportError,
)
from .models import (
    GroupAlarmAlarmPage,
    GroupAlarmAppDevice,
    GroupAlarmOrganization,
    GroupAlarmUser,
    JsonObject,
    JsonValue,
)


def _positive_int(value: object, field: str) -> int:
    """Return a positive integer or reject the payload."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise GroupAlarmResponseError(f"Invalid GroupAlarm field: {field}")
    return value


def _non_negative_int(value: object, field: str) -> int:
    """Return a non-negative integer or reject the payload."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GroupAlarmResponseError(f"Invalid GroupAlarm field: {field}")
    return value


def _json_object(value: JsonValue, context: str) -> JsonObject:
    """Require a JSON object."""
    if not isinstance(value, dict):
        raise GroupAlarmResponseError(f"Unexpected GroupAlarm payload: {context}")
    return value


def _parse_retry_after(value: str | None) -> int | None:
    """Parse Retry-After as seconds, accepting both standard wire forms."""
    if value is None:
        return None
    try:
        seconds = int(value)
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)
        seconds = math.ceil((target - datetime.now(UTC)).total_seconds())
    return max(0, seconds)


class GroupAlarmClient:
    """Typed, Home-Assistant-independent GroupAlarm API client."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: str,
        *,
        base_url: str = BASE_URL,
        request_timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize the client without taking ownership of the session."""
        if not token:
            raise ValueError("token must not be empty")
        self._session = session
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._request_timeout = request_timeout

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Personal-Access-Token": self._token,
        }

    async def _async_request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json_body: JsonObject | None = None,
        expect_json: bool = True,
    ) -> JsonValue:
        url = f"{self._base_url}{path}"
        try:
            async with asyncio.timeout(self._request_timeout):
                async with self._session.request(
                    method,
                    url,
                    headers=self._headers,
                    params=params,
                    json=json_body,
                ) as response:
                    self._raise_for_status(response)
                    if not expect_json:
                        return None

                    content_type = (response.content_type or "").lower()
                    if content_type != "application/json" and not content_type.endswith(
                        "+json"
                    ):
                        raise GroupAlarmResponseError("GroupAlarm response is not JSON")
                    try:
                        payload: Any = await response.json(content_type=None)
                    except (
                        aiohttp.ContentTypeError,
                        json.JSONDecodeError,
                        UnicodeDecodeError,
                        ValueError,
                    ) as err:
                        raise GroupAlarmResponseError(
                            "GroupAlarm returned invalid JSON"
                        ) from err
                    return cast(JsonValue, payload)
        except GroupAlarmError:
            raise
        except TimeoutError as err:
            raise GroupAlarmTimeoutError("GroupAlarm request timed out") from err
        except aiohttp.ClientError as err:
            raise GroupAlarmTransportError(
                "GroupAlarm transport request failed"
            ) from err

    @staticmethod
    def _raise_for_status(response: aiohttp.ClientResponse) -> None:
        status = response.status
        if status < 400:
            return
        if status == 401:
            raise GroupAlarmAuthenticationError(status)
        if status == 403:
            raise GroupAlarmPermissionError(status)
        if status == 429:
            raise GroupAlarmRateLimitError(
                _parse_retry_after(response.headers.get("Retry-After"))
            )
        if status >= 500:
            raise GroupAlarmServerError(status)
        raise GroupAlarmRequestError(status)

    async def async_get_current_user(self) -> GroupAlarmUser:
        """Return the current user, reduced to stable identity data."""
        payload = _json_object(
            await self._async_request("GET", "/user/"),
            "current user",
        )
        return GroupAlarmUser(id=_positive_int(payload.get("id"), "user.id"))

    async def async_get_organizations(
        self,
    ) -> tuple[GroupAlarmOrganization, ...]:
        """Return all accessible organizations."""
        payload = await self._async_request("GET", "/organizations")
        if not isinstance(payload, list):
            raise GroupAlarmResponseError(
                "Unexpected GroupAlarm payload: organizations"
            )

        organizations: list[GroupAlarmOrganization] = []
        for index, item in enumerate(payload):
            organization = _json_object(item, f"organizations[{index}]")
            organization_id = _positive_int(
                organization.get("id"), f"organizations[{index}].id"
            )
            raw_name = organization.get("name")
            name = (
                raw_name.strip()
                if isinstance(raw_name, str) and raw_name.strip()
                else str(organization_id)
            )
            organizations.append(GroupAlarmOrganization(id=organization_id, name=name))
        return tuple(
            sorted(
                organizations,
                key=lambda organization: (
                    organization.name.casefold(),
                    organization.id,
                ),
            )
        )

    async def async_get_app_devices(
        self, owner_id: int
    ) -> tuple[GroupAlarmAppDevice, ...]:
        """Return reduced app devices without retaining push tokens."""
        if owner_id < 1:
            raise ValueError("owner_id must be a positive integer")
        payload = await self._async_request(
            "GET",
            "/app/device",
            params={"owner_id": owner_id},
        )
        if not isinstance(payload, list):
            raise GroupAlarmResponseError("Unexpected GroupAlarm payload: app devices")

        devices: list[GroupAlarmAppDevice] = []
        for index, item in enumerate(payload):
            device = _json_object(item, f"devices[{index}]")
            device_id = _positive_int(device.get("id"), f"devices[{index}].id")
            response_owner_id = _positive_int(
                device.get("ownerID"), f"devices[{index}].ownerID"
            )
            if response_owner_id != owner_id:
                raise GroupAlarmResponseError(
                    "GroupAlarm app device owner does not match the request"
                )
            active = device.get("active")
            if not isinstance(active, bool):
                raise GroupAlarmResponseError(
                    f"Invalid GroupAlarm field: devices[{index}].active"
                )
            is_main_device = device.get("isMainDevice", False)
            if not isinstance(is_main_device, bool):
                raise GroupAlarmResponseError(
                    f"Invalid GroupAlarm field: devices[{index}].isMainDevice"
                )
            raw_name = device.get("name")
            name = (
                raw_name.strip()
                if isinstance(raw_name, str) and raw_name.strip()
                else str(device_id)
            )
            devices.append(
                GroupAlarmAppDevice(
                    id=device_id,
                    owner_id=response_owner_id,
                    name=name,
                    active=active,
                    is_main_device=is_main_device,
                )
            )
        return tuple(devices)

    async def async_get_organization_timeout(self, organization_id: int) -> int:
        """Return an organization's response timeout in seconds."""
        if organization_id < 1:
            raise ValueError("organization_id must be a positive integer")
        payload = _json_object(
            await self._async_request(
                "GET",
                f"/messaging/timeout/{organization_id}",
            ),
            "organization timeout",
        )
        timeout = _positive_int(payload.get("timeout"), "timeout")
        if not 10 <= timeout <= 86400:
            raise GroupAlarmResponseError("Invalid GroupAlarm field: timeout")
        return timeout

    async def async_get_alarms(
        self,
        organization_id: int,
        *,
        limit: int = 10,
        offset: int = 0,
    ) -> GroupAlarmAlarmPage:
        """Return one validated alarm-list page without assuming sort order."""
        if organization_id < 1:
            raise ValueError("organization_id must be a positive integer")
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        if offset < 0:
            raise ValueError("offset must not be negative")
        payload = _json_object(
            await self._async_request(
                "GET",
                "/alarms",
                params={
                    "organization": organization_id,
                    "limit": limit,
                    "offset": offset,
                },
            ),
            "alarm list",
        )
        alarm_values = payload.get("alarms")
        if not isinstance(alarm_values, list):
            raise GroupAlarmResponseError("Unexpected GroupAlarm payload: alarms")

        alarms: list[JsonObject] = []
        for index, item in enumerate(alarm_values):
            alarm = _json_object(item, f"alarms[{index}]")
            _positive_int(alarm.get("id"), f"alarms[{index}].id")
            response_organization_id = alarm.get("organizationID")
            if response_organization_id is not None and (
                _positive_int(
                    response_organization_id,
                    f"alarms[{index}].organizationID",
                )
                != organization_id
            ):
                raise GroupAlarmResponseError(
                    "GroupAlarm alarm organization does not match the request"
                )
            alarms.append(dict(alarm))

        total_alarms = _non_negative_int(payload.get("totalAlarms"), "totalAlarms")
        if total_alarms < len(alarms):
            raise GroupAlarmResponseError("Invalid GroupAlarm field: totalAlarms")
        return GroupAlarmAlarmPage(
            alarms=tuple(alarms),
            total_alarms=total_alarms,
        )

    async def async_get_alarm(self, alarm_id: int) -> JsonObject:
        """Return canonical detail data for one alarm."""
        if alarm_id < 1:
            raise ValueError("alarm_id must be a positive integer")
        payload = _json_object(
            await self._async_request(
                "GET",
                f"/alarm/{alarm_id}",
                params={"update_for_user": "true"},
            ),
            "alarm detail",
        )
        if _positive_int(payload.get("id"), "alarm.id") != alarm_id:
            raise GroupAlarmResponseError(
                "GroupAlarm alarm identity does not match the request"
            )
        return dict(payload)

    async def async_send_feedback(
        self,
        *,
        alarm_id: int,
        organization_id: int,
        user_id: int,
        response: bool,
    ) -> None:
        """Send feedback through the messaging API."""
        if min(alarm_id, organization_id, user_id) < 1:
            raise ValueError("feedback identifiers must be positive integers")
        await self._async_request(
            "POST",
            "/messaging/feedback",
            json_body={
                "alarmID": alarm_id,
                "organizationID": organization_id,
                "response": response,
                "userID": user_id,
            },
            expect_json=False,
        )

    async def async_send_feedback_with_duration(
        self,
        *,
        alarm_id: int,
        device_id: int,
        duration: int,
    ) -> None:
        """Send positive feedback with a traffic duration through the app API."""
        if min(alarm_id, device_id) < 1:
            raise ValueError("feedback identifiers must be positive integers")
        if not 1 <= duration <= MAX_ARRIVAL_DURATION:
            raise ValueError(f"duration must be between 1 and {MAX_ARRIVAL_DURATION}")
        await self._async_request(
            "POST",
            "/app/feedback",
            json_body={
                "alarmID": alarm_id,
                "deviceID": device_id,
                "response": True,
                "answerData": {"duration": duration},
            },
            expect_json=False,
        )
