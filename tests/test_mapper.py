"""Tests for pure GroupAlarm domain normalization."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.groupalarm_ha_connect.api import (
    GroupAlarmAlarmPage,
    GroupAlarmResponseError,
)
from custom_components.groupalarm_ha_connect.mapper import (
    normalize_alarm,
    select_alarm_reference,
    validate_coordinates,
)
from custom_components.groupalarm_ha_connect.models import (
    AlarmActivity,
    DeadlineStatus,
    FeedbackEligibility,
    PersonalFeedback,
)


def _list_alarm(
    alarm_id: int,
    started_at: str,
    *,
    positive: int = 1,
) -> dict[str, object]:
    return {
        "id": alarm_id,
        "organizationID": 7,
        "startDate": started_at,
        "event": {
            "id": 70,
            "organizationID": 7,
            "archived": False,
        },
        "feedbackQuantity": {
            "positive": positive,
            "negative": 2,
            "unknown": 3,
        },
    }


def _detail(
    *,
    alarm_id: int = 11,
    feedback: list[object] | None = None,
) -> dict[str, object]:
    return {
        "id": alarm_id,
        "organizationID": 7,
        "message": "Test alarm",
        "startDate": "2026-07-27T10:00:00Z",
        "endDate": "2026-07-27T10:05:00Z",
        "event": {
            "id": 70,
            "name": "E-123",
            "organizationID": 7,
            "endDate": "2026-07-27T11:00:00Z",
            "scheduledEndtime": "2026-07-27T12:00:00Z",
            "archived": True,
        },
        "feedback": feedback or [],
        "feedbackQuantity": {
            "positive": 4,
            "negative": 1,
            "unknown": 2,
        },
        "optionalContent": {
            "location": {
                "address": "Must not be guessed",
                "latitude": 50.1,
                "longitude": 6.2,
            }
        },
        "feedbackDeadline": "2026-07-27T10:10:00Z",
    }


def test_selects_newest_candidate_by_timestamp_then_id() -> None:
    page = GroupAlarmAlarmPage(
        alarms=(
            _list_alarm(13, "2026-07-27T10:00:00Z"),
            _list_alarm(9, "2026-07-27T11:00:00+00:00"),
            _list_alarm(14, "2026-07-27T11:00:00Z"),
        ),
        total_alarms=3,
    )

    reference = select_alarm_reference(page, 7)

    assert reference is not None
    assert reference.id == 14
    assert reference.started_at == datetime(2026, 7, 27, 11, tzinfo=UTC)
    assert reference.revision.feedback_counts.positive == 1


def test_list_reference_fingerprint_changes_without_retaining_payload() -> None:
    before = select_alarm_reference(
        GroupAlarmAlarmPage(
            alarms=(_list_alarm(11, "2026-07-27T10:00:00Z"),),
            total_alarms=1,
        ),
        7,
    )
    after = select_alarm_reference(
        GroupAlarmAlarmPage(
            alarms=(
                _list_alarm(
                    11,
                    "2026-07-27T10:00:00Z",
                    positive=2,
                ),
            ),
            total_alarms=1,
        ),
        7,
    )

    assert before is not None
    assert after is not None
    assert before != after


def test_empty_alarm_page_and_inconsistent_total() -> None:
    assert (
        select_alarm_reference(
            GroupAlarmAlarmPage(alarms=(), total_alarms=0),
            7,
        )
        is None
    )
    with pytest.raises(GroupAlarmResponseError):
        select_alarm_reference(
            GroupAlarmAlarmPage(alarms=(), total_alarms=1),
            7,
        )


@pytest.mark.parametrize(
    "payload_update",
    [
        {"organizationID": 8},
        {"startDate": "2026-07-27T10:00:00"},
        {"event": None},
    ],
)
def test_rejects_invalid_list_candidate(
    payload_update: dict[str, object],
) -> None:
    payload = _list_alarm(11, "2026-07-27T10:00:00Z")
    payload.update(payload_update)
    with pytest.raises(GroupAlarmResponseError):
        select_alarm_reference(
            GroupAlarmAlarmPage(alarms=(payload,), total_alarms=1),
            7,
        )


@pytest.mark.parametrize(
    ("feedback_value", "expected"),
    [
        (
            {
                "alarmID": 11,
                "userID": 41,
                "state": "RESPONDED",
                "feedback": True,
            },
            PersonalFeedback.POSITIVE,
        ),
        (
            {
                "alarmID": 11,
                "userID": 41,
                "state": "RESPONDED",
                "feedback": False,
            },
            PersonalFeedback.NEGATIVE,
        ),
        (
            {
                "alarmID": 11,
                "userID": 41,
                "state": "TIMEDOUT",
                "feedback": False,
            },
            PersonalFeedback.UNKNOWN,
        ),
        (
            {
                "alarmID": 11,
                "userID": 99,
                "state": "RESPONDED",
                "feedback": True,
            },
            PersonalFeedback.UNKNOWN,
        ),
        (
            {
                "alarmID": 10,
                "userID": 41,
                "state": "RESPONDED",
                "feedback": True,
            },
            PersonalFeedback.UNKNOWN,
        ),
        (
            {
                "alarmID": 11,
                "userID": 41,
                "state": "RESPONDED",
                "feedback": "true",
            },
            PersonalFeedback.UNKNOWN,
        ),
    ],
)
def test_personal_feedback_requires_exact_server_confirmation(
    feedback_value: dict[str, object],
    expected: PersonalFeedback,
) -> None:
    alarm = normalize_alarm(
        _detail(feedback=[feedback_value]),
        alarm_id=11,
        organization_id=7,
        user_id=41,
    )

    assert alarm.personal_feedback is expected
    assert alarm.personal_feedback_duration is None
    assert alarm.deadline_status is (
        DeadlineStatus.ANSWERED
        if expected in (PersonalFeedback.POSITIVE, PersonalFeedback.NEGATIVE)
        else DeadlineStatus.UNKNOWN
    )


def test_personal_feedback_duration_uses_only_matching_confirmed_record() -> None:
    alarm = normalize_alarm(
        _detail(
            feedback=[
                {
                    "alarmID": 11,
                    "userID": 99,
                    "state": "RESPONDED",
                    "feedback": True,
                    "userDuration": 90,
                },
                {
                    "alarmID": 11,
                    "userID": 41,
                    "state": "RESPONDED",
                    "feedback": True,
                    "userDuration": 12,
                },
            ]
        ),
        alarm_id=11,
        organization_id=7,
        user_id=41,
    )

    assert alarm.personal_feedback is PersonalFeedback.POSITIVE
    assert alarm.personal_feedback_duration == 12


@pytest.mark.parametrize("duration", [True, -1, "12"])
def test_invalid_confirmed_personal_duration_is_rejected(duration: object) -> None:
    with pytest.raises(GroupAlarmResponseError):
        normalize_alarm(
            _detail(
                feedback=[
                    {
                        "alarmID": 11,
                        "userID": 41,
                        "state": "RESPONDED",
                        "feedback": True,
                        "userDuration": duration,
                    }
                ]
            ),
            alarm_id=11,
            organization_id=7,
            user_id=41,
        )


def test_normalizer_does_not_invent_blocked_semantics() -> None:
    alarm = normalize_alarm(
        _detail(),
        alarm_id=11,
        organization_id=7,
        user_id=41,
    )

    assert alarm.closed_at == datetime(2026, 7, 27, 10, 5, tzinfo=UTC)
    assert alarm.event_closed_at == datetime(2026, 7, 27, 11, tzinfo=UTC)
    assert alarm.activity is AlarmActivity.UNKNOWN
    assert alarm.feedback_eligibility is FeedbackEligibility.UNKNOWN
    assert alarm.deadline_status is DeadlineStatus.UNKNOWN
    assert alarm.location is None


def test_conflicting_confirmed_feedback_is_rejected() -> None:
    with pytest.raises(GroupAlarmResponseError):
        normalize_alarm(
            _detail(
                feedback=[
                    {
                        "alarmID": 11,
                        "userID": 41,
                        "state": "RESPONDED",
                        "feedback": True,
                    },
                    {
                        "alarmID": 11,
                        "userID": 41,
                        "state": "RESPONDED",
                        "feedback": False,
                    },
                ]
            ),
            alarm_id=11,
            organization_id=7,
            user_id=41,
        )


@pytest.mark.parametrize(
    ("latitude", "longitude", "expected"),
    [
        (50.1, 6.2, (50.1, 6.2)),
        ("50.1", "6.2", (50.1, 6.2)),
        (91, 6.2, None),
        (50.1, 181, None),
        (True, 6.2, None),
        ("nan", 6.2, None),
    ],
)
def test_coordinate_validation(
    latitude: object,
    longitude: object,
    expected: tuple[float, float] | None,
) -> None:
    location = validate_coordinates(latitude, longitude)
    if expected is None:
        assert location is None
    else:
        assert location is not None
        assert (location.latitude, location.longitude) == expected
