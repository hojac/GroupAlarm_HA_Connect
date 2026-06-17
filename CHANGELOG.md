# Changelog

All notable changes to this project will be documented in this file.

---

## [0.2.3] - 2026-06-17

### Added

* Added active alarming binary sensor (`Aktive Alarmierung`)
* Added countdown sensor for feedback deadline
* Added feedback deadline end sensor
* Added device tracker for alarm location
* Added multi-organization support
* Added automatic organization discovery
* Added Home Assistant Config Flow
* Added Home Assistant Options Flow

### Changed

* Renamed `Aktiver Einsatz` to `Aktive Alarmierung`
* Renamed `Einsatzende` to `Rückmeldefrist Ende`
* Improved dashboard compatibility
* Improved feedback handling

### Fixed

* Fixed timestamp handling for Home Assistant timestamp sensors
* Fixed feedback synchronization after button press
* Fixed alarm update handling
* Fixed API refresh after feedback submission

---

## [0.2.2] - 2026-06-17

### Added

* Initial feedback support
* Alarm reload after feedback submission

### Fixed

* Fixed communication with GroupAlarm feedback endpoint
* Fixed sensor update issues

---

## [0.2.1] - 2026-06-17

### Fixed

* Fixed timestamp parsing
* Fixed Home Assistant device class timestamp compatibility

---

## [0.2.0] - 2026-06-17

### Added

* Automatic organization discovery
* Multi-organization support
* Config Flow
* Options Flow
* Device Tracker support
* Dashboard example

---

## [0.1.0] - 2026-06-17

### Added

* Initial release
* Alarm sensors
* Feedback buttons
* Alarm location support
* GroupAlarm API integration
