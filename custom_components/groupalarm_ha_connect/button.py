"""Fail-safe personal feedback buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.components.persistent_notification import async_create
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.translation import async_get_translations

from .api import (
    GroupAlarmAuthenticationError,
    GroupAlarmError,
    GroupAlarmPermissionError,
    GroupAlarmRateLimitError,
    GroupAlarmRequestError,
)
from .const import DOMAIN
from .coordinator import GroupAlarmCoordinator
from .entity import GroupAlarmEntity
from .feedback import (
    FeedbackActionError,
    FeedbackBusyError,
    FeedbackConfigurationError,
    FeedbackConflictError,
    FeedbackDeliveryResult,
    FeedbackNotConfirmedError,
    FeedbackOutcomeUnknownError,
    FeedbackPendingError,
    FeedbackSupersededError,
    FeedbackUnavailableError,
)
from .models import GroupAlarmConfigEntry

BUTTONS: tuple[tuple[ButtonEntityDescription, bool], ...] = (
    (
        ButtonEntityDescription(
            key="feedback_komme",
            translation_key="feedback_positive",
            icon="mdi:account-check",
        ),
        True,
    ),
    (
        ButtonEntityDescription(
            key="feedback_komme_nicht",
            translation_key="feedback_negative",
            icon="mdi:account-cancel",
        ),
        False,
    ),
)

_ACTION_EXCEPTION_KEYS: tuple[tuple[type[FeedbackActionError], str], ...] = (
    (FeedbackUnavailableError, "feedback_unavailable"),
    (FeedbackBusyError, "feedback_busy"),
    (FeedbackPendingError, "feedback_pending"),
    (FeedbackConfigurationError, "feedback_configuration"),
    (FeedbackNotConfirmedError, "feedback_not_confirmed"),
    (FeedbackOutcomeUnknownError, "feedback_outcome_unknown"),
    (FeedbackSupersededError, "feedback_superseded"),
    (FeedbackConflictError, "feedback_conflict"),
)

_NOTIFICATION_FALLBACKS = {
    "feedback_sent_without_duration": (
        "Feedback was sent, but the arrival time could not be transmitted."
    ),
    "feedback_duration_unverified": (
        "Feedback was confirmed, but the arrival time could not be verified."
    ),
}


def _service_error(key: str) -> ServiceValidationError:
    """Return a translated, payload-free button service error."""
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
    )


def _action_exception_key(error: FeedbackActionError) -> str:
    """Map a sanitized domain failure to a translation key."""
    for error_type, key in _ACTION_EXCEPTION_KEYS:
        if isinstance(error, error_type):
            return key
    return "feedback_failed"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GroupAlarmConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up two feedback buttons for every configured organization."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        GroupAlarmFeedbackButton(
            coordinator,
            organization_id,
            description,
            response,
        )
        for organization_id in coordinator.organization_names
        for description, response in BUTTONS
    )


class GroupAlarmFeedbackButton(GroupAlarmEntity, ButtonEntity):
    """Send feedback only while the domain model proves it is safe."""

    entity_description: ButtonEntityDescription

    def __init__(
        self,
        coordinator: GroupAlarmCoordinator,
        organization_id: int,
        description: ButtonEntityDescription,
        response: bool,
    ) -> None:
        """Initialize a stable feedback button."""
        super().__init__(coordinator, organization_id, description.key)
        self.entity_description = description
        self._response = response

    @property
    def available(self) -> bool:
        """Disable the button for unknown eligibility, pending writes and locks."""
        return super().available and self.coordinator.can_send_feedback(
            self.organization_id
        )

    async def _async_notify_degraded_result(
        self,
        result: FeedbackDeliveryResult,
    ) -> None:
        """Inform the user without turning a confirmed fallback into a failure."""
        key = {
            FeedbackDeliveryResult.CONFIRMED_WITHOUT_DURATION: (
                "feedback_sent_without_duration"
            ),
            FeedbackDeliveryResult.CONFIRMED_DURATION_UNVERIFIED: (
                "feedback_duration_unverified"
            ),
        }.get(result)
        if key is None:
            return

        translations = await async_get_translations(
            self.hass,
            self.hass.config.language,
            "exceptions",
            {DOMAIN},
        )
        message = translations.get(
            f"component.{DOMAIN}.exceptions.{key}.message",
            _NOTIFICATION_FALLBACKS[key],
        )
        async_create(
            self.hass,
            message,
            title="GroupAlarm HA Connect",
            notification_id=f"{DOMAIN}_feedback_{self.organization_id}",
        )

    async def async_press(self) -> None:
        """Send and reconcile one positive or negative feedback action."""
        try:
            result = await self.coordinator.async_send_feedback(
                self.organization_id,
                response=self._response,
            )
        except GroupAlarmAuthenticationError as err:
            self.coordinator.entry.async_start_reauth(self.hass)
            raise _service_error("feedback_authentication") from err
        except GroupAlarmPermissionError as err:
            raise _service_error("feedback_permission") from err
        except GroupAlarmRateLimitError as err:
            raise _service_error("feedback_rate_limited") from err
        except GroupAlarmRequestError as err:
            raise _service_error("feedback_rejected") from err
        except FeedbackActionError as err:
            raise _service_error(_action_exception_key(err)) from err
        except GroupAlarmError as err:
            raise _service_error("feedback_failed") from err

        await self._async_notify_degraded_result(result)
