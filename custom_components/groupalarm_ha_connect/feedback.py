"""Domain results and safe failures for personal feedback delivery."""

from __future__ import annotations

from enum import StrEnum


class FeedbackDeliveryResult(StrEnum):
    """Server-confirmed outcome of one feedback action."""

    CONFIRMED = "confirmed"
    CONFIRMED_WITHOUT_DURATION = "confirmed_without_duration"
    CONFIRMED_DURATION_UNVERIFIED = "confirmed_duration_unverified"


class FeedbackActionError(Exception):
    """Base class for sanitized feedback action failures."""


class FeedbackUnavailableError(FeedbackActionError):
    """The current snapshot does not prove that feedback can be sent."""


class FeedbackBusyError(FeedbackActionError):
    """The same alarm already has a feedback action in flight."""


class FeedbackPendingError(FeedbackActionError):
    """An earlier write still has an unknown or unconfirmed outcome."""


class FeedbackConfigurationError(FeedbackActionError):
    """The configured duration cannot be sent with the stored device."""


class FeedbackNotConfirmedError(FeedbackActionError):
    """The API accepted the write but bounded GET reconciliation did not confirm it."""


class FeedbackOutcomeUnknownError(FeedbackActionError):
    """A write's transport outcome remains unknown after reconciliation."""


class FeedbackSupersededError(FeedbackActionError):
    """A newer alarm replaced the target during reconciliation."""


class FeedbackConflictError(FeedbackActionError):
    """The server confirmed the opposite response for the target alarm."""
