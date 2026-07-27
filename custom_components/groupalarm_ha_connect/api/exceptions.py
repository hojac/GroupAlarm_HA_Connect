"""Safe exception hierarchy for the GroupAlarm API."""

from __future__ import annotations


class GroupAlarmError(Exception):
    """Base class for GroupAlarm client errors."""


class GroupAlarmTransportError(GroupAlarmError):
    """The request did not produce an unambiguous HTTP response."""


class GroupAlarmTimeoutError(GroupAlarmTransportError):
    """The request timed out."""


class GroupAlarmResponseError(GroupAlarmError):
    """The API returned an unexpected or invalid response."""


class GroupAlarmHttpError(GroupAlarmError):
    """Base class for sanitized HTTP status errors."""

    def __init__(self, status: int) -> None:
        """Initialize a status-only exception."""
        self.status = status
        super().__init__(f"GroupAlarm request failed with HTTP {status}")


class GroupAlarmAuthenticationError(GroupAlarmHttpError):
    """The Personal Access Token was rejected."""


class GroupAlarmPermissionError(GroupAlarmHttpError):
    """The authenticated account lacks permission."""


class GroupAlarmRequestError(GroupAlarmHttpError):
    """The API rejected a request as invalid."""


class GroupAlarmRateLimitError(GroupAlarmHttpError):
    """The API rate limit was reached."""

    def __init__(self, retry_after: int | None) -> None:
        """Initialize a sanitized rate-limit error."""
        self.retry_after = retry_after
        super().__init__(429)


class GroupAlarmServerError(GroupAlarmHttpError):
    """The API returned a temporary server error."""
