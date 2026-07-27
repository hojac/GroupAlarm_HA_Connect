"""Config-entry coordinator with traffic-minimizing GroupAlarm polling."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from time import monotonic

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    GroupAlarmAuthenticationError,
    GroupAlarmClient,
    GroupAlarmError,
    GroupAlarmPermissionError,
    GroupAlarmRateLimitError,
    GroupAlarmRequestError,
    GroupAlarmResponseError,
    GroupAlarmServerError,
    GroupAlarmTransportError,
    GroupAlarmUser,
)
from .const import (
    ALARM_GATE_LIMIT,
    CONF_FEEDBACK_DEVICE_ID,
    CONF_ORGANIZATION_DURATIONS,
    DETAIL_SAFETY_REFRESH,
    DOMAIN,
    FEEDBACK_RECONCILIATION_DELAYS,
    MAX_ARRIVAL_DURATION,
    MAX_PARALLEL_ORGANIZATIONS,
    MIN_ARRIVAL_DURATION,
)
from .feedback import (
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
from .mapper import normalize_alarm, select_alarm_reference
from .models import (
    AlarmReference,
    FeedbackEligibility,
    GroupAlarmAlarm,
    GroupAlarmConfigEntry,
    GroupAlarmCoordinatorData,
    OrganizationError,
    OrganizationSnapshot,
    PersonalFeedback,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _OrganizationResult:
    """One successful or failed organization refresh."""

    organization_id: int
    alarm: GroupAlarmAlarm | None = None
    error: GroupAlarmError | None = None


def _classify_error(error: GroupAlarmError) -> OrganizationError:
    """Convert a sanitized API exception to a stable domain error."""
    if isinstance(error, GroupAlarmPermissionError):
        return OrganizationError.PERMISSION
    if isinstance(error, GroupAlarmRateLimitError):
        return OrganizationError.RATE_LIMIT
    if isinstance(error, GroupAlarmRequestError):
        return OrganizationError.REQUEST
    if isinstance(error, GroupAlarmResponseError):
        return OrganizationError.RESPONSE
    if isinstance(error, GroupAlarmServerError):
        return OrganizationError.SERVER
    if isinstance(error, GroupAlarmTransportError):
        return OrganizationError.TRANSPORT
    raise TypeError(f"Unsupported GroupAlarm exception: {type(error).__name__}")


class GroupAlarmCoordinator(DataUpdateCoordinator[GroupAlarmCoordinatorData]):
    """Poll all configured organizations through one coordinated update."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: GroupAlarmConfigEntry,
        client: GroupAlarmClient,
        user: GroupAlarmUser,
        organization_names: dict[int, str],
        scan_interval: int,
    ) -> None:
        """Initialize a comparable, bounded-concurrency coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
            always_update=False,
        )
        self.entry = entry
        self.client = client
        self.user = user
        self.organization_names = dict(sorted(organization_names.items()))
        self._semaphore = asyncio.Semaphore(MAX_PARALLEL_ORGANIZATIONS)
        self._references: dict[int, AlarmReference] = {}
        self._alarms: dict[int, GroupAlarmAlarm] = {}
        self._detail_loaded_at: dict[int, float] = {}
        self._errors: dict[int, OrganizationError | None] = dict.fromkeys(
            organization_names
        )
        self._feedback_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._pending_feedback: dict[tuple[int, int], bool] = {}
        self._last_successful_update: datetime | None = None

    @property
    def last_successful_update(self) -> datetime | None:
        """Return the timestamp of the latest update with usable data."""
        return self._last_successful_update

    def snapshot(self, organization_id: int) -> OrganizationSnapshot:
        """Return one organization snapshot from coordinator memory."""
        return self.data.for_organization(organization_id)

    @staticmethod
    def _feedback_key(organization_id: int, alarm_id: int) -> tuple[int, int]:
        """Return the lock and pending-state identity for one alarm."""
        return organization_id, alarm_id

    def _clear_pending_feedback(
        self,
        organization_id: int,
        *,
        keep_alarm_id: int | None = None,
    ) -> None:
        """Discard pending writes that no longer belong to the current alarm."""
        for key in tuple(self._pending_feedback):
            if key[0] == organization_id and key[1] != keep_alarm_id:
                self._pending_feedback.pop(key, None)

    def _resolve_pending_feedback(self, alarm: GroupAlarmAlarm) -> None:
        """Clear a pending write only after a matching canonical GET."""
        key = self._feedback_key(alarm.organization_id, alarm.id)
        if key not in self._pending_feedback:
            return
        expected = (
            PersonalFeedback.POSITIVE
            if self._pending_feedback[key]
            else PersonalFeedback.NEGATIVE
        )
        if alarm.personal_feedback is expected:
            self._pending_feedback.pop(key, None)

    def _validated_feedback_alarm(self, organization_id: int) -> GroupAlarmAlarm:
        """Return an eligible current alarm or reject the action fail-safe."""
        try:
            snapshot = self.snapshot(organization_id)
        except (AttributeError, KeyError) as err:
            raise FeedbackUnavailableError from err
        alarm = snapshot.alarm
        if (
            not snapshot.available
            or alarm is None
            or alarm.feedback_eligibility is not FeedbackEligibility.OPEN
            or alarm.personal_feedback is not PersonalFeedback.UNKNOWN
        ):
            raise FeedbackUnavailableError
        key = self._feedback_key(organization_id, alarm.id)
        if key in self._pending_feedback:
            raise FeedbackPendingError
        return alarm

    def is_feedback_in_progress(
        self,
        organization_id: int,
        alarm_id: int,
    ) -> bool:
        """Return whether an action currently owns the alarm's send lock."""
        lock = self._feedback_locks.get(self._feedback_key(organization_id, alarm_id))
        return lock is not None and lock.locked()

    def can_send_feedback(self, organization_id: int) -> bool:
        """Return whether a button can safely start a feedback action."""
        try:
            alarm = self._validated_feedback_alarm(organization_id)
        except (FeedbackUnavailableError, FeedbackPendingError):
            return False
        return not self.is_feedback_in_progress(organization_id, alarm.id)

    def _arrival_duration(self, organization_id: int) -> int | None:
        """Return one validated configured duration."""
        raw_durations = self.entry.options.get(CONF_ORGANIZATION_DURATIONS, {})
        if not isinstance(raw_durations, dict):
            raise FeedbackConfigurationError
        raw_duration: object = raw_durations.get(
            str(organization_id),
            raw_durations.get(organization_id),
        )
        if raw_duration is None:
            return None
        if (
            isinstance(raw_duration, bool)
            or not isinstance(raw_duration, int)
            or not MIN_ARRIVAL_DURATION <= raw_duration <= MAX_ARRIVAL_DURATION
        ):
            raise FeedbackConfigurationError
        return raw_duration

    def _feedback_device_id(self) -> int:
        """Return the explicitly selected positive feedback device."""
        device_id = self.entry.options.get(CONF_FEEDBACK_DEVICE_ID)
        if isinstance(device_id, bool) or not isinstance(device_id, int):
            raise FeedbackConfigurationError
        if device_id < 1:
            raise FeedbackConfigurationError
        return device_id

    def _target_is_current(self, organization_id: int, alarm_id: int) -> bool:
        """Return whether reconciliation still belongs to the selected alarm."""
        reference = self._references.get(organization_id)
        return reference is not None and reference.id == alarm_id

    def _publish_reconciled_alarm(self, alarm: GroupAlarmAlarm) -> None:
        """Publish canonical detail obtained after a feedback write."""
        if not self._target_is_current(alarm.organization_id, alarm.id):
            raise FeedbackSupersededError
        self._alarms[alarm.organization_id] = alarm
        self._detail_loaded_at[alarm.organization_id] = monotonic()
        self._resolve_pending_feedback(alarm)

        snapshots = tuple(
            replace(snapshot, alarm=alarm)
            if snapshot.organization_id == alarm.organization_id
            else snapshot
            for snapshot in self.data.organizations
        )
        self.async_set_updated_data(GroupAlarmCoordinatorData(organizations=snapshots))

    async def _async_reconcile_feedback(
        self,
        *,
        organization_id: int,
        alarm_id: int,
        response: bool,
        duration: int | None,
    ) -> FeedbackDeliveryResult | None:
        """Perform a bounded canonical GET reconciliation."""
        expected = PersonalFeedback.POSITIVE if response else PersonalFeedback.NEGATIVE
        duration_unverified = False

        for delay in FEEDBACK_RECONCILIATION_DELAYS:
            if not self._target_is_current(organization_id, alarm_id):
                raise FeedbackSupersededError
            if delay:
                await asyncio.sleep(delay)
            if not self._target_is_current(organization_id, alarm_id):
                raise FeedbackSupersededError

            try:
                detail = await self.client.async_get_alarm(alarm_id)
                alarm = normalize_alarm(
                    detail,
                    alarm_id=alarm_id,
                    organization_id=organization_id,
                    user_id=self.user.id,
                )
            except GroupAlarmAuthenticationError:
                raise
            except GroupAlarmError:
                continue

            self._publish_reconciled_alarm(alarm)
            if alarm.personal_feedback is expected:
                if (
                    duration is not None
                    and alarm.personal_feedback_duration != duration
                ):
                    duration_unverified = True
                    continue
                return FeedbackDeliveryResult.CONFIRMED
            if alarm.personal_feedback in (
                PersonalFeedback.POSITIVE,
                PersonalFeedback.NEGATIVE,
            ):
                self._pending_feedback.pop(
                    self._feedback_key(organization_id, alarm_id),
                    None,
                )
                raise FeedbackConflictError

        if duration_unverified:
            return FeedbackDeliveryResult.CONFIRMED_DURATION_UNVERIFIED
        return None

    def _mark_feedback_pending(
        self,
        organization_id: int,
        alarm_id: int,
        response: bool,
    ) -> None:
        """Retain an unresolved write so a regular poll forces canonical detail."""
        self._pending_feedback[self._feedback_key(organization_id, alarm_id)] = response

    async def _async_send_standard_feedback(
        self,
        *,
        organization_id: int,
        alarm_id: int,
        response: bool,
    ) -> FeedbackDeliveryResult:
        """Send standard feedback and require a matching canonical GET."""
        try:
            await self.client.async_send_feedback(
                alarm_id=alarm_id,
                organization_id=organization_id,
                user_id=self.user.id,
                response=response,
            )
        except (GroupAlarmServerError, GroupAlarmTransportError):
            self._mark_feedback_pending(organization_id, alarm_id, response)
            reconciled = await self._async_reconcile_feedback(
                organization_id=organization_id,
                alarm_id=alarm_id,
                response=response,
                duration=None,
            )
            if reconciled is not None:
                return reconciled
            raise FeedbackOutcomeUnknownError from None

        self._mark_feedback_pending(organization_id, alarm_id, response)
        reconciled = await self._async_reconcile_feedback(
            organization_id=organization_id,
            alarm_id=alarm_id,
            response=response,
            duration=None,
        )
        if reconciled is not None:
            return reconciled
        raise FeedbackNotConfirmedError

    async def _async_deliver_feedback(
        self,
        *,
        organization_id: int,
        alarm_id: int,
        response: bool,
    ) -> FeedbackDeliveryResult:
        """Choose one endpoint and reconcile without a blind second POST."""
        duration = self._arrival_duration(organization_id) if response else None
        if duration is None:
            return await self._async_send_standard_feedback(
                organization_id=organization_id,
                alarm_id=alarm_id,
                response=response,
            )

        device_id = self._feedback_device_id()
        try:
            await self.client.async_send_feedback_with_duration(
                alarm_id=alarm_id,
                device_id=device_id,
                duration=duration,
            )
        except GroupAlarmRequestError:
            await self._async_send_standard_feedback(
                organization_id=organization_id,
                alarm_id=alarm_id,
                response=True,
            )
            return FeedbackDeliveryResult.CONFIRMED_WITHOUT_DURATION
        except (GroupAlarmServerError, GroupAlarmTransportError):
            self._mark_feedback_pending(organization_id, alarm_id, True)
            reconciled = await self._async_reconcile_feedback(
                organization_id=organization_id,
                alarm_id=alarm_id,
                response=True,
                duration=duration,
            )
            if reconciled is not None:
                return reconciled
            raise FeedbackOutcomeUnknownError from None

        self._mark_feedback_pending(organization_id, alarm_id, True)
        reconciled = await self._async_reconcile_feedback(
            organization_id=organization_id,
            alarm_id=alarm_id,
            response=True,
            duration=duration,
        )
        if reconciled is not None:
            return reconciled
        raise FeedbackNotConfirmedError

    async def async_send_feedback(
        self,
        organization_id: int,
        *,
        response: bool,
    ) -> FeedbackDeliveryResult:
        """Send one feedback action under a non-queuing per-alarm lock."""
        alarm = self._validated_feedback_alarm(organization_id)
        key = self._feedback_key(organization_id, alarm.id)
        lock = self._feedback_locks.setdefault(key, asyncio.Lock())
        if lock.locked():
            raise FeedbackBusyError

        await lock.acquire()
        self.async_update_listeners()
        try:
            current_alarm = self._validated_feedback_alarm(organization_id)
            if current_alarm.id != alarm.id:
                raise FeedbackSupersededError
            return await self._async_deliver_feedback(
                organization_id=organization_id,
                alarm_id=alarm.id,
                response=response,
            )
        finally:
            lock.release()
            self._feedback_locks.pop(key, None)
            self.async_update_listeners()

    async def _async_update_organization(
        self,
        organization_id: int,
    ) -> _OrganizationResult:
        """Run the list gate and conditionally load canonical detail."""
        async with self._semaphore:
            try:
                page = await self.client.async_get_alarms(
                    organization_id,
                    limit=ALARM_GATE_LIMIT,
                )
                reference = select_alarm_reference(page, organization_id)
                if reference is None:
                    self._clear_pending_feedback(organization_id)
                    self._references.pop(organization_id, None)
                    self._alarms.pop(organization_id, None)
                    self._detail_loaded_at.pop(organization_id, None)
                    return _OrganizationResult(organization_id=organization_id)

                previous_reference = self._references.get(organization_id)
                if (
                    previous_reference is not None
                    and previous_reference.id != reference.id
                ):
                    self._clear_pending_feedback(
                        organization_id,
                        keep_alarm_id=reference.id,
                    )
                loaded_at = self._detail_loaded_at.get(organization_id)
                safety_refresh_due = (
                    loaded_at is None
                    or monotonic() - loaded_at >= DETAIL_SAFETY_REFRESH.total_seconds()
                )
                detail_required = (
                    previous_reference != reference
                    or organization_id not in self._alarms
                    or safety_refresh_due
                    or self._feedback_key(organization_id, reference.id)
                    in self._pending_feedback
                )
                if detail_required:
                    detail = await self.client.async_get_alarm(reference.id)
                    alarm = normalize_alarm(
                        detail,
                        alarm_id=reference.id,
                        organization_id=organization_id,
                        user_id=self.user.id,
                    )
                    self._alarms[organization_id] = alarm
                    self._detail_loaded_at[organization_id] = monotonic()
                    self._resolve_pending_feedback(alarm)

                self._references[organization_id] = reference
                return _OrganizationResult(
                    organization_id=organization_id,
                    alarm=self._alarms[organization_id],
                )
            except GroupAlarmAuthenticationError:
                raise
            except GroupAlarmError as err:
                return _OrganizationResult(
                    organization_id=organization_id,
                    error=err,
                )

    def _previous_alarm(self, organization_id: int) -> GroupAlarmAlarm | None:
        """Return retained canonical state without exposing raw payloads."""
        if self.data is not None:
            try:
                return self.data.for_organization(organization_id).alarm
            except KeyError:
                pass
        return self._alarms.get(organization_id)

    def _log_error_transition(
        self,
        organization_id: int,
        current: OrganizationError | None,
    ) -> None:
        """Log one message on failure and one on recovery."""
        previous = self._errors.get(organization_id)
        if current == previous:
            return
        if current is None:
            _LOGGER.info(
                "GroupAlarm organization %s recovered",
                organization_id,
            )
        else:
            _LOGGER.warning(
                "GroupAlarm organization %s update failed (%s)",
                organization_id,
                current,
            )
        self._errors[organization_id] = current

    async def _async_update_data(self) -> GroupAlarmCoordinatorData:
        """Fetch every organization with bounded parallelism and isolation."""
        results = await asyncio.gather(
            *(
                self._async_update_organization(organization_id)
                for organization_id in self.organization_names
            ),
            return_exceptions=True,
        )

        organization_results: list[_OrganizationResult] = []
        for result in results:
            if isinstance(result, GroupAlarmAuthenticationError):
                raise ConfigEntryAuthFailed(
                    "GroupAlarm credentials were rejected"
                ) from result
            if isinstance(result, BaseException):
                raise result
            organization_results.append(result)

        successful = tuple(
            result for result in organization_results if result.error is None
        )
        if not successful:
            retry_after = max(
                (
                    result.error.retry_after
                    for result in organization_results
                    if isinstance(result.error, GroupAlarmRateLimitError)
                    and result.error.retry_after is not None
                ),
                default=None,
            )
            raise UpdateFailed(
                "Unable to update any GroupAlarm organization",
                retry_after=retry_after,
            )

        snapshots: list[OrganizationSnapshot] = []
        for result in organization_results:
            error = _classify_error(result.error) if result.error is not None else None
            self._log_error_transition(result.organization_id, error)
            snapshots.append(
                OrganizationSnapshot(
                    user_id=self.user.id,
                    organization_id=result.organization_id,
                    organization_name=self.organization_names[result.organization_id],
                    available=error is None,
                    error=error,
                    alarm=(
                        result.alarm
                        if error is None
                        else self._previous_alarm(result.organization_id)
                    ),
                )
            )

        self._last_successful_update = datetime.now(UTC)
        return GroupAlarmCoordinatorData(organizations=tuple(snapshots))
