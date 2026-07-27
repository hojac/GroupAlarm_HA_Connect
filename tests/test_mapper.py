"""Tests for pure GroupAlarm domain normalization."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.groupalarm_ha_connect.api import (
    GroupAlarmAlarmPage,
    GroupAlarmResponseError,
)
from custom_components.groupalarm_ha_connect.mapper import (
    _feedback_counts,
    _optional_bool,
    _optional_non_negative_int,
    _optional_positive_int,
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


def test_optional_mapper_scalars_preserve_missing_values() -> None:
    """Absent optional wire values stay absent and invalid booleans fail."""
    assert _optional_positive_int(None, "value") is None
    assert _optional_non_negative_int(None, "value") is None
    assert _optional_bool(None, "value") is None
    assert _feedback_counts(None, "counts").positive is None
    with pytest.raises(GroupAlarmResponseError, match="value"):
        _optional_bool("false", "value")


@pytest.mark.parametrize(
    "payload_update",
    [
        {"startDate": None},
        {"startDate": "not-a-date"},
        {"event": {"id": 70, "organizationID": 8}},
        {
            "event": {
                "id": 70,
                "organizationID": 7,
                "abort": "invalid",
            }
        },
    ],
)
def test_additional_list_candidate_boundaries(
    payload_update: dict[str, object],
) -> None:
    """Malformed time and nested event fields fail the small polling gate."""
    payload = _list_alarm(11, "2026-07-27T10:00:00Z")
    payload.update(payload_update)
    with pytest.raises(GroupAlarmResponseError):
        select_alarm_reference(
            GroupAlarmAlarmPage(alarms=(payload,), total_alarms=1),
            7,
        )


def test_list_reference_accepts_documented_abort_shape() -> None:
    """An abort object contributes only its proven revision timestamp."""
    payload = _list_alarm(11, "2026-07-27T10:00:00Z")
    payload["event"] = {
        "id": 70,
        "organizationID": 7,
        "abort": {"time": "2026-07-27T10:01:00Z"},
    }
    reference = select_alarm_reference(
        GroupAlarmAlarmPage(alarms=(payload,), total_alarms=1),
        7,
    )
    assert reference is not None
    assert reference.revision.event_abort_present is True
    assert reference.revision.event_abort_at == datetime(
        2026,
        7,
        27,
        10,
        1,
        tzinfo=UTC,
    )


def test_invalid_list_scope_is_rejected_before_mapping() -> None:
    """An invalid organization identity never enters selection."""
    with pytest.raises(ValueError, match="organization_id"):
        select_alarm_reference(
            GroupAlarmAlarmPage(alarms=(), total_alarms=0),
            0,
        )


@pytest.mark.parametrize("feedback", [None, {}, ["invalid"]])
def test_personal_feedback_container_boundaries(feedback: object) -> None:
    """Only a list of object records can confirm personal feedback."""
    payload = _detail()
    payload["feedback"] = feedback
    if feedback == ["invalid"]:
        alarm = normalize_alarm(
            payload,
            alarm_id=11,
            organization_id=7,
            user_id=41,
        )
        assert alarm.personal_feedback is PersonalFeedback.UNKNOWN
    else:
        with pytest.raises(GroupAlarmResponseError, match="feedback"):
            normalize_alarm(
                payload,
                alarm_id=11,
                organization_id=7,
                user_id=41,
            )


@pytest.mark.parametrize(
    ("argument_updates", "payload_updates"),
    [
        ({"alarm_id": 0}, {}),
        ({}, {"id": 12}),
        ({}, {"organizationID": 8}),
        ({}, {"message": None}),
        ({}, {"event": {"name": "E", "organizationID": 8}}),
        ({}, {"event": {"name": None, "organizationID": 7}}),
        (
            {},
            {
                "event": {
                    "name": "E",
                    "organizationID": 7,
                    "abort": "invalid",
                }
            },
        ),
    ],
)
def test_alarm_detail_identity_and_shape_boundaries(
    argument_updates: dict[str, int],
    payload_updates: dict[str, object],
) -> None:
    """Canonical details reject mismatched identities and malformed fields."""
    arguments = {"alarm_id": 11, "organization_id": 7, "user_id": 41}
    arguments.update(argument_updates)
    payload = _detail()
    payload.update(payload_updates)
    with pytest.raises((ValueError, GroupAlarmResponseError)):
        normalize_alarm(payload, **arguments)


def test_blank_event_name_is_normalized_to_missing() -> None:
    """Whitespace-only optional labels do not become visible content."""
    payload = _detail()
    event = dict(payload["event"])  # type: ignore[arg-type]
    event["name"] = "  "
    payload["event"] = event
    assert (
        normalize_alarm(
            payload,
            alarm_id=11,
            organization_id=7,
            user_id=41,
        ).event_name
        is None
    )


def test_coordinate_parser_rejects_non_numeric_strings() -> None:
    """Text that has no finite numeric representation is not a location."""
    assert validate_coordinates("north", "east") is None
