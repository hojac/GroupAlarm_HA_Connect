"""Config-entry coordinator with traffic-minimizing GroupAlarm polling."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from math import ceil
from time import monotonic

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_track_time_interval
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
    DeadlineStatus,
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


@dataclass(frozen=True, slots=True)
class _FeedbackWindow:
    """One locally measured feedback window for a detected alarm."""

    alarm_id: int
    deadline: datetime


def _utcnow() -> datetime:
    """Return the current UTC time behind one testable boundary."""
    return datetime.now(UTC)


def _apply_feedback_window(
    alarm: GroupAlarmAlarm,
    window: _FeedbackWindow | None,
    now: datetime,
) -> GroupAlarmAlarm:
    """Project a local feedback window onto canonical server state."""
    if window is None or window.alarm_id != alarm.id:
        return alarm

    if alarm.personal_feedback in (
        PersonalFeedback.POSITIVE,
        PersonalFeedback.NEGATIVE,
    ):
        return replace(
            alarm,
            feedback_eligibility=FeedbackEligibility.CLOSED,
            feedback_deadline=window.deadline,
            deadline_status=DeadlineStatus.ANSWERED,
        )
    if now >= window.deadline:
        return replace(
            alarm,
            feedback_eligibility=FeedbackEligibility.CLOSED,
            feedback_deadline=window.deadline,
            deadline_status=DeadlineStatus.KNOWN_EXPIRED,
        )
    if alarm.feedback_eligibility is not FeedbackEligibility.CLOSED:
        return replace(
            alarm,
            feedback_deadline=window.deadline,
            deadline_status=DeadlineStatus.KNOWN_ACTIVE,
        )
    return replace(
        alarm,
        feedback_deadline=window.deadline,
        deadline_status=DeadlineStatus.UNKNOWN,
    )


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
        self._feedback_windows: dict[int, _FeedbackWindow] = {}
        self._unsub_countdown: Callable[[], None] | None = None
        self._last_successful_update: datetime | None = None

    @property
    def last_successful_update(self) -> datetime | None:
        """Return the timestamp of the latest update with usable data."""
        return self._last_successful_update

    def snapshot(self, organization_id: int) -> OrganizationSnapshot:
        """Return one organization snapshot from coordinator memory."""
        return self.data.for_organization(organization_id)

    def feedback_countdown(self, organization_id: int) -> int | None:
        """Return whole local seconds remaining, clamped at zero."""
        try:
            alarm = self.snapshot(organization_id).alarm
        except (AttributeError, KeyError):
            return None
        if (
            alarm is None
            or alarm.feedback_deadline is None
            or alarm.deadline_status
            not in (
                DeadlineStatus.KNOWN_ACTIVE,
                DeadlineStatus.KNOWN_EXPIRED,
            )
        ):
            return None
        return max(
            0,
            ceil((alarm.feedback_deadline - _utcnow()).total_seconds()),
        )

    def _stop_countdown(self) -> None:
        """Remove the single local countdown listener."""
        if self._unsub_countdown is None:
            return
        self._unsub_countdown()
        self._unsub_countdown = None

    @staticmethod
    def _has_running_countdown(
        data: GroupAlarmCoordinatorData,
        now: datetime,
    ) -> bool:
        """Return whether at least one feedback window still needs ticks."""
        return any(
            snapshot.alarm is not None
            and snapshot.alarm.feedback_deadline is not None
            and snapshot.alarm.deadline_status is DeadlineStatus.KNOWN_ACTIVE
            and now < snapshot.alarm.feedback_deadline
            for snapshot in data.organizations
        )

    def _sync_countdown(
        self,
        data: GroupAlarmCoordinatorData,
        now: datetime,
    ) -> None:
        """Run exactly one local ticker while any feedback window is active."""
        if self._has_running_countdown(data, now):
            if self._unsub_countdown is None:
                self._unsub_countdown = async_track_time_interval(
                    self.hass,
                    self._async_countdown_tick,
                    timedelta(seconds=1),
                    cancel_on_shutdown=True,
                )
            return
        self._stop_countdown()

    @callback
    def _async_countdown_tick(self, now: datetime) -> None:
        """Publish one local countdown tick without any API request."""
        snapshots: list[OrganizationSnapshot] = []
        changed = False
        for snapshot in self.data.organizations:
            alarm = snapshot.alarm
            if alarm is None:
                snapshots.append(snapshot)
                continue
            updated_alarm = _apply_feedback_window(
                alarm,
                self._feedback_windows.get(snapshot.organization_id),
                now,
            )
            if updated_alarm != alarm:
                changed = True
                self._alarms[snapshot.organization_id] = updated_alarm
                snapshots.append(replace(snapshot, alarm=updated_alarm))
            else:
                snapshots.append(snapshot)

        data = GroupAlarmCoordinatorData(organizations=tuple(snapshots))
        running = self._has_running_countdown(data, now)
        if changed or running:
            self.async_set_updated_data(data)
        self._sync_countdown(data, now)

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
            or alarm.feedback_deadline is None
            or alarm.deadline_status is not DeadlineStatus.KNOWN_ACTIVE
            or _utcnow() >= alarm.feedback_deadline
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
        alarm = _apply_feedback_window(
            alarm,
            self._feedback_windows.get(alarm.organization_id),
            _utcnow(),
        )
        self._alarms[alarm.organization_id] = alarm
        self._detail_loaded_at[alarm.organization_id] = monotonic()
        self._resolve_pending_feedback(alarm)

        snapshots = tuple(
            replace(snapshot, alarm=alarm)
            if snapshot.organization_id == alarm.organization_id
            else snapshot
            for snapshot in self.data.organizations
        )
        data = GroupAlarmCoordinatorData(organizations=snapshots)
        self.async_set_updated_data(data)
        self._sync_countdown(data, _utcnow())

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
        current_alarm = self._validated_feedback_alarm(organization_id)
        if current_alarm.id != alarm_id:
            raise FeedbackSupersededError
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
            current_alarm = self._validated_feedback_alarm(organization_id)
            if current_alarm.id != alarm_id:
                raise FeedbackSupersededError from None
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
                    self._feedback_windows.pop(organization_id, None)
                    return _OrganizationResult(organization_id=organization_id)

                previous_reference = self._references.get(organization_id)
                window = self._feedback_windows.get(organization_id)
                window_required = window is None or window.alarm_id != reference.id
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
                    or window_required
                )
                if detail_required:
                    if window_required:
                        detected_at = _utcnow()
                        detail, timeout = await asyncio.gather(
                            self.client.async_get_alarm(reference.id),
                            self.client.async_get_organization_timeout(organization_id),
                        )
                        window = _FeedbackWindow(
                            alarm_id=reference.id,
                            deadline=detected_at + timedelta(seconds=timeout),
                        )
                        self._feedback_windows[organization_id] = window
                    else:
                        detail = await self.client.async_get_alarm(reference.id)
                    alarm = normalize_alarm(
                        detail,
                        alarm_id=reference.id,
                        organization_id=organization_id,
                        user_id=self.user.id,
                    )
                    alarm = _apply_feedback_window(alarm, window, _utcnow())
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

        now = _utcnow()
        self._last_successful_update = now
        data = GroupAlarmCoordinatorData(organizations=tuple(snapshots))
        self._sync_countdown(data, now)
        return data

    async def async_shutdown(self) -> None:
        """Stop local countdown work before coordinator shutdown."""
        self._stop_countdown()
        await super().async_shutdown()
