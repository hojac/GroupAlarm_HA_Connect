from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .const import BASE_URL


class GroupAlarmApiError(Exception):
    """GroupAlarm API error."""


class GroupAlarmApiClient:
    def __init__(self, session: aiohttp.ClientSession, token: str, base_url: str = BASE_URL) -> None:
        self._session = session
        self._token = token
        self._base_url = base_url.rstrip("/")

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Personal-Access-Token": self._token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self._base_url}{path}"
        try:
            async with asyncio.timeout(30):
                async with self._session.request(method, url, headers=self.headers, **kwargs) as resp:
                    if resp.status >= 400:
                        text = await resp.text()
                        raise GroupAlarmApiError(f"{method} {path} failed: HTTP {resp.status}: {text}")
                    if resp.content_type == "application/json":
                        return await resp.json()
                    return await resp.text()
        except TimeoutError as exc:
            raise GroupAlarmApiError(f"Timeout while calling {method} {path}") from exc
        except aiohttp.ClientError as exc:
            raise GroupAlarmApiError(str(exc)) from exc

    async def get_current_user(self) -> dict[str, Any]:
        return await self._request("GET", "/user/")

    async def get_organizations(self) -> list[dict[str, Any]]:
        """Return all organizations accessible by the current token."""
        data = await self._request("GET", "/organizations/?all=true")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("organizations", "entries", "items"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
        return []

    async def get_latest_alarm(self, organization_id: int) -> dict[str, Any] | None:
        data = await self._request("GET", f"/alarms?limit=1&organization={organization_id}")
        alarms = data.get("alarms", []) if isinstance(data, dict) else []
        return alarms[0] if alarms else None

    async def get_alarm(self, alarm_id: int, *, update_for_user: bool = True) -> dict[str, Any] | None:
        """Return the full alarm payload for one alarm."""
        suffix = "?update_for_user=true" if update_for_user else ""
        data = await self._request("GET", f"/alarm/{alarm_id}{suffix}")
        return data if isinstance(data, dict) else None

    async def set_feedback(self, alarm_id: int, organization_id: int, user_id: int, response: bool) -> bool:
        data = await self._request(
            "POST",
            "/messaging/feedback",
            json={
                "alarmID": alarm_id,
                "organizationID": organization_id,
                "response": response,
                "userID": user_id,
            },
        )
        return bool(data.get("success", True)) if isinstance(data, dict) else True
