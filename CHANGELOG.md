# Changelog

All notable changes to this project will be documented in this file.

## [0.3.0] - 2026-06-17

### Breaking changes
- Changed integration domain from `groupalarm` to `groupalarm_ha_connect`.
- Changed custom component folder from `custom_components/groupalarm` to `custom_components/groupalarm_ha_connect`.
- Existing installations using the old domain must remove the old integration and add the new one again.

### Changed
- Corrected project name to **GroupAlarm HA Connect**.
- Updated HACS metadata and manifest URLs.

## [0.2.3] - 2026-06-17

### Added
- Added `Aktive Alarmierung` binary sensor.
- Added `Rückmeldefrist Ende` timestamp sensor.
- Added `Rückmeldefrist Countdown` sensor.
- Added automatic disabling of feedback buttons after the feedback deadline.

### Changed
- Renamed alarm-state wording from Einsatz-focused naming to alarm-window naming.
- Confirmed feedback remains visible after the feedback deadline expires.

## [0.2.2] - 2026-06-17

### Changed
- Feedback is posted via `/api/v1/messaging/feedback`.
- Feedback state is only updated after server confirmation.
- Full alarm reload after feedback submission via `/alarm/{alarmID}?update_for_user=true`.

## [0.2.1] - 2026-06-17

### Fixed
- Fixed timestamp handling for Home Assistant timestamp sensors.
- Fixed feedback synchronization after button press.

## [0.2.0] - 2026-06-17

### Added
- Automatic organization discovery.
- Multi-organization support.
- Options Flow for organization selection and scan interval.
- Device tracker for alarm location.

## [0.1.0] - 2026-06-17

### Added
- Initial test release.
- Alarm sensors.
- Feedback buttons.
- Basic GroupAlarm API polling.
