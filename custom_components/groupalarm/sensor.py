from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import GroupAlarmCoordinator


def _get_path(data: dict[str, Any] | None, *keys: str, default: Any = None) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _parse_datetime(value: Any) -> datetime | None:
    """Return a timezone-aware datetime for Home Assistant timestamp sensors."""
    if value in (None, "", "unknown", "unavailable"):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _response_to_state(response: Any) -> str | None:
    """Convert GroupAlarm feedback variants to the public sensor state."""
    if isinstance(response, dict):
        for key in ("response", "feedback", "value", "positive"):
            if key in response:
                return _response_to_state(response[key])
    if response is True:
        return "komme"
    if response is False:
        return "komme_nicht"
    if isinstance(response, str):
        normalized = response.strip().lower()
        if normalized in ("true", "positive", "positiv", "komme", "yes", "ja"):
            return "komme"
        if normalized in ("false", "negative", "negativ", "komme_nicht", "nein", "no"):
            return "komme_nicht"
    return None


def _feedback_item_user_id(item: dict[str, Any]) -> Any:
    user = item.get("user")
    if isinstance(user, dict):
        return user.get("id", user.get("userID", user.get("userId")))
    return item.get("userID", item.get("userId", item.get("user_id", user)))


def _feedback_value(coordinator: GroupAlarmCoordinator) -> str:
    alarm = coordinator.alarm
    uid = coordinator.user_id
    if not alarm:
        return "offen"

    # Some endpoints may already include the current user's feedback directly.
    for key in ("selfFeedback", "ownFeedback", "myFeedback"):
        if key in alarm:
            state = _response_to_state(alarm.get(key))
            if state:
                return state

    # Otherwise, try to find the current user in the alarm feedback list.
    if uid:
        for item in alarm.get("feedback", []) or []:
            if not isinstance(item, dict):
                continue
            item_uid = _feedback_item_user_id(item)
            try:
                matches_user = item_uid is not None and int(item_uid) == int(uid)
            except (TypeError, ValueError):
                matches_user = False
            if matches_user:
                for key in ("response", "feedback", "value", "positive"):
                    if key in item:
                        state = _response_to_state(item.get(key))
                        if state:
                            return state

    # If GroupAlarm acknowledged our POST but the list endpoint does not expose
    # per-user feedback, keep the confirmed server response for this alarm.
    confirmed = coordinator.confirmed_feedback_state
    if confirmed:
        return confirmed

    return "offen"


def _alarm_end(coordinator: GroupAlarmCoordinator) -> datetime | None:
    return _parse_datetime(_get_path(coordinator.alarm, "endDate"))


def _format_countdown(end: datetime | None) -> str:
    if end is None:
        return "unbekannt"
    now = dt_util.utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    remaining = int((end - now).total_seconds())
    if remaining <= 0:
        return "abgelaufen"
    minutes, seconds = divmod(remaining, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(key="alarm_id", name="Alarm ID"),
    SensorEntityDescription(key="message", name="Einsatzmeldung"),
    SensorEntityDescription(key="start", name="Alarmierung Start", device_class=SensorDeviceClass.TIMESTAMP),
    SensorEntityDescription(key="end", name="Rückmeldefrist Ende", device_class=SensorDeviceClass.TIMESTAMP),
    SensorEntityDescription(key="countdown", name="Rückmeldefrist Countdown"),
    SensorEntityDescription(key="event", name="Einsatznummer"),
    SensorEntityDescription(key="address", name="Einsatzort"),
    SensorEntityDescription(key="latitude", name="Latitude"),
    SensorEntityDescription(key="longitude", name="Longitude"),
    SensorEntityDescription(key="feedback_positive", name="Rückmeldungen Positive"),
    SensorEntityDescription(key="feedback_negative", name="Rückmeldungen Negative"),
    SensorEntityDescription(key="feedback_unknown", name="Rückmeldungen Offen"),
    SensorEntityDescription(key="my_feedback", name="Meine Rückmeldung"),
    SensorEntityDescription(key="user_id", name="User ID"),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinators: dict[int, GroupAlarmCoordinator] = hass.data[DOMAIN][entry.entry_id]
    entities: list[GroupAlarmSensor] = []
    for coordinator in coordinators.values():
        entities.extend(GroupAlarmSensor(coordinator, entry, desc) for desc in SENSORS)
    async_add_entities(entities)


class GroupAlarmSensor(CoordinatorEntity[GroupAlarmCoordinator], SensorEntity):
    entity_description: SensorEntityDescription

    def __init__(self, coordinator: GroupAlarmCoordinator, entry: ConfigEntry, description: SensorEntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{coordinator.organization_id}_{description.key}"
        self._attr_has_entity_name = True
        self._attr_translation_key = description.key
        self._attr_device_info = coordinator.device_info
        self._unsub_countdown: CALLBACK_TYPE | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.entity_description.key == "countdown":
            self._unsub_countdown = async_track_time_interval(
                self.hass,
                self._async_countdown_tick,
                timedelta(seconds=1),
            )
            self.async_on_remove(self._unsub_countdown)

    @callback
    def _async_countdown_tick(self, now: datetime) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> Any:
        alarm = self.coordinator.alarm
        key = self.entity_description.key
        if key == "alarm_id":
            return _get_path(alarm, "id")
        if key == "message":
            return _get_path(alarm, "message")
        if key == "start":
            return _parse_datetime(_get_path(alarm, "startDate"))
        if key == "end":
            return _alarm_end(self.coordinator)
        if key == "countdown":
            if not alarm:
                return "kein Alarm"
            return _format_countdown(_alarm_end(self.coordinator))
        if key == "event":
            return _get_path(alarm, "event", "name")
        if key == "address":
            return _get_path(alarm, "optionalContent", "location", "address", default=_get_path(alarm, "optionalContent", "address"))
        if key == "latitude":
            return _get_path(alarm, "optionalContent", "location", "latitude", default=_get_path(alarm, "optionalContent", "latitude"))
        if key == "longitude":
            return _get_path(alarm, "optionalContent", "location", "longitude", default=_get_path(alarm, "optionalContent", "longitude"))
        if key == "feedback_positive":
            return _get_path(alarm, "feedbackQuantity", "positive", default=0)
        if key == "feedback_negative":
            return _get_path(alarm, "feedbackQuantity", "negative", default=0)
        if key == "feedback_unknown":
            return _get_path(alarm, "feedbackQuantity", "unknown", default=0)
        if key == "my_feedback":
            return _feedback_value(self.coordinator)
        if key == "user_id":
            return self.coordinator.user_id
        return None
