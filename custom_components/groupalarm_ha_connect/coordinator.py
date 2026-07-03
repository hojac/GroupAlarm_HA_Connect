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
    """Return the real alarm/event close timestamp, not the feedback deadline."""
    return _parse_datetime(_get_path(alarm, "endDate")) or _parse_datetime(_get_path(alarm, "event", "endDate"))


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
        self._confirmed_feedback_alarm_id: int | None = None
        self._confirmed_feedback_state: str | None = None

    @property
    def alarm(self) -> dict[str, Any] | None:
        return self.data.get("alarm") if self.data else None

    @property
    def user_id(self) -> int | None:
        if self.user:
            return self.user.get("id")
        return None

    @property
    def confirmed_feedback_state(self) -> str | None:
        if not self.alarm or self._confirmed_feedback_alarm_id is None:
            return None
        try:
            alarm_id = int(self.alarm.get("id"))
        except (TypeError, ValueError):
            return None
        if alarm_id == self._confirmed_feedback_alarm_id:
            return self._confirmed_feedback_state
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
                if self._confirmed_feedback_alarm_id is not None and alarm_id != self._confirmed_feedback_alarm_id:
                    self._confirmed_feedback_alarm_id = None
                    self._confirmed_feedback_state = None
            return {"alarm": alarm, "user": self.user}
        except GroupAlarmApiError as exc:
            raise UpdateFailed(str(exc)) from exc

    async def async_set_feedback(self, response: bool) -> None:
        if not self.alarm or not self.user_id:
            raise GroupAlarmApiError("No alarm or user available")
        if not self.is_alert_active:
            raise GroupAlarmApiError("Alarmierung ist nicht aktiv; Rückmeldung nicht möglich")
        alarm_id = int(self.alarm["id"])

        # The UI state must only change after GroupAlarm accepted the feedback.
        await self.api.set_feedback(
            alarm_id=alarm_id,
            organization_id=self.organization_id,
            user_id=int(self.user_id),
            response=response,
        )

        # POST was accepted by the server. Keep this confirmed state for the
        # current alarm, because the alarm list endpoint does not always expose
        # the current user's individual feedback immediately.
        self._confirmed_feedback_alarm_id = alarm_id
        self._confirmed_feedback_state = "komme" if response else "komme_nicht"

        # Prefer the full alarm payload after feedback. It may contain richer
        # feedback/selfFeedback data than the paginated alarm list endpoint.
        try:
            full_alarm = await self.api.get_alarm(alarm_id, update_for_user=True)
        except GroupAlarmApiError:
            full_alarm = None

        if full_alarm is not None:
            self.async_set_updated_data({"alarm": full_alarm, "user": self.user})
        else:
            await self.async_request_refresh()
