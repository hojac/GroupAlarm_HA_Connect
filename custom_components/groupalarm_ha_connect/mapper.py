"""Pure normalization for GroupAlarm list and detail payloads."""

from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite

from .api import GroupAlarmAlarmPage, GroupAlarmResponseError, JsonObject
from .models import (
    AlarmActivity,
    AlarmLocation,
    AlarmReference,
    AlarmRevision,
    DeadlineStatus,
    FeedbackCounts,
    FeedbackEligibility,
    GroupAlarmAlarm,
    PersonalFeedback,
)


def _positive_int(value: object, field: str) -> int:
    """Return a positive integer or reject the payload."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise GroupAlarmResponseError(f"Invalid GroupAlarm field: {field}")
    return value


def _optional_positive_int(value: object, field: str) -> int | None:
    """Validate an optional positive integer."""
    if value is None:
        return None
    return _positive_int(value, field)


def _optional_non_negative_int(value: object, field: str) -> int | None:
    """Validate an optional non-negative integer."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GroupAlarmResponseError(f"Invalid GroupAlarm field: {field}")
    return value


def _object(value: object, field: str) -> JsonObject:
    """Require a JSON object."""
    if not isinstance(value, dict):
        raise GroupAlarmResponseError(f"Invalid GroupAlarm field: {field}")
    return value


def _optional_bool(value: object, field: str) -> bool | None:
    """Validate an optional boolean."""
    if value is None:
        return None
    if not isinstance(value, bool):
        raise GroupAlarmResponseError(f"Invalid GroupAlarm field: {field}")
    return value


def _datetime(value: object, field: str) -> datetime:
    """Parse a timezone-aware ISO timestamp and normalize it to UTC."""
    if not isinstance(value, str) or not value:
        raise GroupAlarmResponseError(f"Invalid GroupAlarm field: {field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise GroupAlarmResponseError(f"Invalid GroupAlarm field: {field}") from err
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GroupAlarmResponseError(f"Invalid GroupAlarm field: {field}")
    return parsed.astimezone(UTC)


def _optional_datetime(value: object, field: str) -> datetime | None:
    """Validate an optional timezone-aware ISO timestamp."""
    if value in (None, ""):
        return None
    return _datetime(value, field)


def _feedback_counts(value: object, field: str) -> FeedbackCounts:
    """Normalize optional aggregate feedback counts."""
    if value is None:
        return FeedbackCounts(positive=None, negative=None, unknown=None)
    payload = _object(value, field)
    return FeedbackCounts(
        positive=_optional_non_negative_int(
            payload.get("positive"), f"{field}.positive"
        ),
        negative=_optional_non_negative_int(
            payload.get("negative"), f"{field}.negative"
        ),
        unknown=_optional_non_negative_int(payload.get("unknown"), f"{field}.unknown"),
    )


def _alarm_reference(
    payload: JsonObject,
    organization_id: int,
) -> AlarmReference:
    """Normalize one list candidate into a small alarm reference."""
    alarm_id = _positive_int(payload.get("id"), "alarm.id")
    response_organization_id = _positive_int(
        payload.get("organizationID"), "alarm.organizationID"
    )
    if response_organization_id != organization_id:
        raise GroupAlarmResponseError(
            "GroupAlarm alarm organization does not match the request"
        )

    event = _object(payload.get("event"), "alarm.event")
    event_organization_id = event.get("organizationID")
    if event_organization_id is not None and (
        _positive_int(event_organization_id, "alarm.event.organizationID")
        != organization_id
    ):
        raise GroupAlarmResponseError(
            "GroupAlarm event organization does not match the request"
        )

    abort = event.get("abort")
    abort_payload: JsonObject | None = None
    if abort is not None:
        abort_payload = _object(abort, "alarm.event.abort")

    return AlarmReference(
        id=alarm_id,
        organization_id=organization_id,
        started_at=_datetime(payload.get("startDate"), "alarm.startDate"),
        revision=AlarmRevision(
            alarm_closed_at=_optional_datetime(payload.get("endDate"), "alarm.endDate"),
            event_id=_optional_positive_int(event.get("id"), "alarm.event.id"),
            event_closed_at=_optional_datetime(
                event.get("endDate"), "alarm.event.endDate"
            ),
            event_archived=_optional_bool(
                event.get("archived"), "alarm.event.archived"
            ),
            event_abort_present=abort_payload is not None,
            event_abort_at=(
                _optional_datetime(abort_payload.get("time"), "alarm.event.abort.time")
                if abort_payload is not None
                else None
            ),
            feedback_counts=_feedback_counts(
                payload.get("feedbackQuantity"), "alarm.feedbackQuantity"
            ),
        ),
    )


def select_alarm_reference(
    page: GroupAlarmAlarmPage,
    organization_id: int,
) -> AlarmReference | None:
    """Select the newest candidate within a bounded page deterministically."""
    if organization_id < 1:
        raise ValueError("organization_id must be a positive integer")
    if not page.alarms:
        if page.total_alarms:
            raise GroupAlarmResponseError(
                "GroupAlarm returned an empty first page for existing alarms"
            )
        return None

    references = tuple(
        _alarm_reference(alarm, organization_id) for alarm in page.alarms
    )
    return max(references, key=lambda reference: (reference.started_at, reference.id))


def _personal_feedback(
    value: object,
    *,
    alarm_id: int,
    user_id: int,
) -> tuple[PersonalFeedback, int | None, FeedbackEligibility]:
    """Return matching personal feedback and response eligibility."""
    if not isinstance(value, list):
        raise GroupAlarmResponseError("Invalid GroupAlarm field: alarm.feedback")

    confirmed: set[PersonalFeedback] = set()
    durations: set[int] = set()
    matching_states: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        item_alarm_id = item.get("alarmID")
        item_user_id = item.get("userID")
        if (
            isinstance(item_alarm_id, bool)
            or not isinstance(item_alarm_id, int)
            or isinstance(item_user_id, bool)
            or not isinstance(item_user_id, int)
            or item_alarm_id != alarm_id
            or item_user_id != user_id
        ):
            continue
        state = item.get("state")
        if not isinstance(state, str):
            continue
        matching_states.add(state)
        if state != "RESPONDED":
            continue
        feedback = item.get("feedback")
        if feedback is True:
            confirmed.add(PersonalFeedback.POSITIVE)
        elif feedback is False:
            confirmed.add(PersonalFeedback.NEGATIVE)
        else:
            continue

        duration = item.get("userDuration")
        if duration is not None:
            durations.add(
                _optional_non_negative_int(
                    duration,
                    "alarm.feedback[].userDuration",
                )
                or 0
            )

    if len(confirmed) > 1:
        raise GroupAlarmResponseError(
            "GroupAlarm returned conflicting personal feedback"
        )
    eligibility = FeedbackEligibility.UNKNOWN
    if matching_states:
        if matching_states == {"WAITING"}:
            eligibility = FeedbackEligibility.OPEN
        elif matching_states <= {"RESPONDED", "TIMEDOUT", "UNAVAILABLE"}:
            eligibility = FeedbackEligibility.CLOSED
    if confirmed:
        duration = next(iter(durations)) if len(durations) == 1 else None
        return next(iter(confirmed)), duration, FeedbackEligibility.CLOSED
    return PersonalFeedback.UNKNOWN, None, eligibility


def _location(_value: object) -> AlarmLocation | None:
    """Keep location blocked until a real fixture proves its JSON paths."""
    return None


def normalize_alarm(
    payload: JsonObject,
    *,
    alarm_id: int,
    organization_id: int,
    user_id: int,
) -> GroupAlarmAlarm:
    """Normalize canonical alarm detail without a flat list/detail merge."""
    if min(alarm_id, organization_id, user_id) < 1:
        raise ValueError("alarm identifiers must be positive integers")
    response_alarm_id = _positive_int(payload.get("id"), "alarm.id")
    if response_alarm_id != alarm_id:
        raise GroupAlarmResponseError(
            "GroupAlarm alarm identity does not match the request"
        )
    response_organization_id = _positive_int(
        payload.get("organizationID"), "alarm.organizationID"
    )
    if response_organization_id != organization_id:
        raise GroupAlarmResponseError(
            "GroupAlarm alarm organization does not match the request"
        )

    message = payload.get("message")
    if not isinstance(message, str):
        raise GroupAlarmResponseError("Invalid GroupAlarm field: alarm.message")

    event = _object(payload.get("event"), "alarm.event")
    event_organization_id = _positive_int(
        event.get("organizationID"), "alarm.event.organizationID"
    )
    if event_organization_id != organization_id:
        raise GroupAlarmResponseError(
            "GroupAlarm event organization does not match the request"
        )
    event_name_value = event.get("name")
    if not isinstance(event_name_value, str):
        raise GroupAlarmResponseError("Invalid GroupAlarm field: alarm.event.name")
    event_name = event_name_value.strip() or None

    abort = event.get("abort")
    if abort is not None:
        _object(abort, "alarm.event.abort")
    closed_at = _optional_datetime(payload.get("endDate"), "alarm.endDate")

    (
        personal_feedback,
        personal_feedback_duration,
        feedback_eligibility,
    ) = _personal_feedback(
        payload.get("feedback"),
        alarm_id=alarm_id,
        user_id=user_id,
    )
    deadline_status = (
        DeadlineStatus.ANSWERED
        if personal_feedback in (PersonalFeedback.POSITIVE, PersonalFeedback.NEGATIVE)
        else DeadlineStatus.UNKNOWN
    )
    if closed_at is not None:
        feedback_eligibility = FeedbackEligibility.CLOSED

    return GroupAlarmAlarm(
        id=alarm_id,
        organization_id=organization_id,
        message=message,
        started_at=_datetime(payload.get("startDate"), "alarm.startDate"),
        closed_at=closed_at,
        event_id=_optional_positive_int(event.get("id"), "alarm.event.id"),
        event_name=event_name,
        event_closed_at=_optional_datetime(event.get("endDate"), "alarm.event.endDate"),
        event_archived=_optional_bool(event.get("archived"), "alarm.event.archived"),
        event_abort_present=abort is not None,
        feedback_counts=_feedback_counts(
            payload.get("feedbackQuantity"), "alarm.feedbackQuantity"
        ),
        personal_feedback=personal_feedback,
        personal_feedback_duration=personal_feedback_duration,
        # Alarm activity remains separate from the feedback window.
        activity=AlarmActivity.UNKNOWN,
        feedback_eligibility=feedback_eligibility,
        feedback_deadline=None,
        deadline_status=deadline_status,
        location=_location(payload.get("optionalContent")),
    )


def validate_coordinates(latitude: object, longitude: object) -> AlarmLocation | None:
    """Validate a future fixture-backed coordinate mapping."""
    if (
        isinstance(latitude, bool)
        or isinstance(longitude, bool)
        or not isinstance(latitude, str | int | float)
        or not isinstance(longitude, str | int | float)
    ):
        return None
    try:
        latitude_value = float(latitude)
        longitude_value = float(longitude)
    except (TypeError, ValueError):
        return None
    if (
        not isfinite(latitude_value)
        or not isfinite(longitude_value)
        or not -90 <= latitude_value <= 90
        or not -180 <= longitude_value <= 180
    ):
        return None
    return AlarmLocation(
        address=None,
        latitude=latitude_value,
        longitude=longitude_value,
    )
