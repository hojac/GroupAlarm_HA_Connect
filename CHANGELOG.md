# Changelog

## 0.3.5

### Changed
- Config flow now supports multiple integration instances for the same GroupAlarm user/token when different organization selections are used.
- Duplicate protection is now based on token hash and selected organization IDs instead of only the GroupAlarm user ID.

## [0.3.4] - 2026-06-19

### Changed
- Updated `icon.png` and `logo.png` with the final GroupAlarm HA Connect branding.
- Added optimized 256×256 integration icon for HACS/Home Assistant display.
- Updated integration version to 0.3.4.

## [0.3.3] - 2026-06-17

### Added
- Added project icon and logo assets for HACS/Home Assistant display.

### Changed
- Updated integration version to 0.3.3.

All notable changes to this project will be documented in this file.

## [0.3.2] - 2026-06-17

### Changed
- Changed device name prefix to **GroupAlarm HA Connect** so new installations create clearer Entity-IDs such as `sensor.groupalarm_ha_connect_<organization>_...`.
- Updated Config Flow entry titles to **GroupAlarm HA Connect**.
- Updated README notes for Entity-ID naming.

### Notes
- Home Assistant does not allow hyphens in Entity-IDs, so the Entity-ID prefix is `groupalarm_ha_connect`, not `groupalarm-ha-connect`.
- Existing entity IDs are not renamed automatically by Home Assistant. Remove and re-add the integration if you want the new IDs generated automatically.

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
