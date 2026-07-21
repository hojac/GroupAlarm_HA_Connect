from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GroupAlarmApiClient, GroupAlarmApiError
from .const import DOMAIN


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, "", "unknown", "unavailable"):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        parsed = dt_util.parse_datetime(value)
        if parsed is None:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _get_path(data: dict[str, Any] | None, *keys: str) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _alarm_closed_at(alarm: dict[str, Any] | None) -> datetime | None:
    """Return the event close timestamp, excluding the feedback deadline."""
    return _parse_datetime(_get_path(alarm, "event", "endDate"))


def _alarm_id(alarm: dict[str, Any] | None) -> int | None:
    try:
        return int(_get_path(alarm, "id"))
    except (TypeError, ValueError):
        return None


class GroupAlarmCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        api: GroupAlarmApiClient,
        organization_id: int,
        organization_name: str,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name=f"{DOMAIN}_{organization_id}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.api = api
        self.organization_id = organization_id
        self.organization_name = organization_name
        self.user: dict[str, Any] | None = None

    @property
    def alarm(self) -> dict[str, Any] | None:
        return self.data.get("alarm") if self.data else None

    @property
    def user_id(self) -> int | None:
        if self.user:
            return self.user.get("id")
        return None

    @property
    def is_alert_active(self) -> bool:
        """Return true for the latest alarm while its event/alarm is not closed.

        GroupAlarm also exposes deadline-like fields such as scheduledEndtime.
        Those values are feedback/auto-close metadata and must not hide an
        otherwise still open alarm from the dashboard.
        """
        alarm = self.alarm
        if _alarm_id(alarm) is None:
            return False
        if _alarm_closed_at(alarm) is not None:
            return False
        event = _get_path(alarm, "event")
        if isinstance(event, dict) and event.get("archived") is True:
            return False
        return True

    @property
    def device_info(self) -> dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, str(self.organization_id))},
            "name": f"GroupAlarm HA Connect {self.organization_name}",
            "manufacturer": "GroupAlarm",
            "entry_type": "service",
        }

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            if self.user is None:
                self.user = await self.api.get_current_user()
            alarm = await self.api.get_latest_alarm(self.organization_id)

            # The paginated /alarms endpoint may omit endDate / own feedback details.
            # For the current latest alarm, load the full alarm payload as the canonical
            # state source so countdown and button colors are based on the server value.
            if alarm is not None:
                alarm_id = _alarm_id(alarm)
                if alarm_id is not None:
                    full_alarm = await self.api.get_alarm(alarm_id, update_for_user=True)
                    if full_alarm is not None:
                        alarm = {**alarm, **full_alarm}
            return {"alarm": alarm, "user": self.user}
        except GroupAlarmApiError as exc:
            raise UpdateFailed(str(exc)) from exc

    async def async_set_feedback(self, response: bool) -> None:
        if not self.alarm or not self.user_id:
            raise GroupAlarmApiError("No alarm or user available")
        if not self.is_alert_active:
            raise GroupAlarmApiError("Alarmierung ist nicht aktiv; Rückmeldung nicht möglich")
        alarm_id = int(self.alarm["id"])

        # Sending and displaying feedback are deliberately separate. A successful
        # POST only means that GroupAlarm accepted the request; it must never
        # change the displayed personal feedback on its own.
        await self.api.set_feedback(
            alarm_id=alarm_id,
            organization_id=self.organization_id,
            user_id=int(self.user_id),
            response=response,
        )

        # Only a subsequent full GET response may update the button color.
        try:
            full_alarm = await self.api.get_alarm(alarm_id, update_for_user=True)
        except GroupAlarmApiError:
            full_alarm = None

        if full_alarm is not None and _alarm_id(full_alarm) == alarm_id:
            self.async_set_updated_data({"alarm": full_alarm, "user": self.user})
        else:
            await self.async_request_refresh()
