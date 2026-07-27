"""Config-entry coordinator with traffic-minimizing GroupAlarm polling."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
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
    DETAIL_SAFETY_REFRESH,
    DOMAIN,
    MAX_PARALLEL_ORGANIZATIONS,
)
from .mapper import normalize_alarm, select_alarm_reference
from .models import (
    AlarmReference,
    GroupAlarmAlarm,
    GroupAlarmConfigEntry,
    GroupAlarmCoordinatorData,
    OrganizationError,
    OrganizationSnapshot,
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

    def snapshot(self, organization_id: int) -> OrganizationSnapshot:
        """Return one organization snapshot from coordinator memory."""
        return self.data.for_organization(organization_id)

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
                    self._references.pop(organization_id, None)
                    self._alarms.pop(organization_id, None)
                    self._detail_loaded_at.pop(organization_id, None)
                    return _OrganizationResult(organization_id=organization_id)

                previous_reference = self._references.get(organization_id)
                loaded_at = self._detail_loaded_at.get(organization_id)
                safety_refresh_due = (
                    loaded_at is None
                    or monotonic() - loaded_at >= DETAIL_SAFETY_REFRESH.total_seconds()
                )
                detail_required = (
                    previous_reference != reference
                    or organization_id not in self._alarms
                    or safety_refresh_due
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

        return GroupAlarmCoordinatorData(organizations=tuple(snapshots))
