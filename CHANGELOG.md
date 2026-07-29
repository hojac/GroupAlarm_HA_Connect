# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Fixed

- Migrate the legacy `end` and `countdown` sensors onto their v0.5 identities
  without creating `_2` entities, and remove obsolete `latitude`/`longitude`
  registry entries.
- Derive active alarm state independently from top-level `alarm.endDate` and
  `event.abort`, without coupling it to feedback or countdown state.

## [0.5.1] - 2026-07-29

### Added

- Complete asynchronous integration rewrite for Home Assistant `2026.6.0`.
- Multi-organization coordinator with a traffic-minimizing alarm-list gate.
- Stable account-, organization-, device-, and entity-level identities.
- UI setup, reauthentication, reconfigure, options reload, and tested
  Config Entry migration.
- Fail-safe feedback pipeline with bounded GET reconciliation, non-queuing
  per-alarm locks, pending-write protection, and no blind duplicate POST.
- Privacy-preserving diagnostics, actionable invalid-device repair issue, and
  repository safety validation.
- Reproducible Ruff, Mypy, Pytest, coverage, Hassfest, and HACS CI.
- German and English translations and a state-safe wall-display template.
- Local per-alarm feedback deadline and seconds countdown based on the
  organization timeout loaded when a new alarm ID is detected.

### Changed

- Requires Home Assistant `2026.6.0` or newer.
- Alarm details load only for a new or changed alarm reference, pending
  reconciliation, or the 15-minute safety refresh.
- Personal feedback is shown only after matching canonical detail confirms it.
- Matching `WAITING` feedback enables buttons only while the local countdown
  is above zero; expiry is rechecked immediately before every feedback POST.
- Documentation no longer treats `alarm.endDate`, an event end, or an arrival
  duration as a personal feedback deadline.

### Removed

- Legacy synchronous architecture, unsafe fallback fields, tracked Python cache
  files, token-derived Config Entry identities, and optimistic feedback state.

### Known limitations

- Activity and location mappings still need additional current real-payload
  evidence before they can leave `unknown` or `unavailable`.
- GroupAlarm does not expose the server notification timestamp used for its own
  timeout. The displayed cutoff is therefore local to Home Assistant and starts
  when the integration detects a new alarm ID.
- The alarm-list API does not document ordering, so a bounded first page cannot
  formally guarantee the globally newest alarm.

## [0.3.10] - 2026-07-24

### Added
- Optionale Standard-Anfahrtszeit je Organisationseinheit.
- Auswahl eines vorhandenen aktiven GroupAlarm-Geräts, sobald mindestens eine Anfahrtszeit konfiguriert ist.
- Positive Rückmeldungen mit Zeit werden über `/app/feedback` und `answerData.duration` gesendet.
- Automatischer Fallback über `/messaging/feedback`, falls die Zeitübermittlung fehlschlägt; Home Assistant informiert über die ausgelassene Zeit.

### Fixed
- Das Integrationssymbol wird aus dem von Home Assistant erwarteten lokalen `brand`-Ordner geladen.
- Der Countdown aktualisiert sich nur noch sekündlich, solange eine bekannte Rückmeldefrist tatsächlich läuft.
- Der veraltete `TrackerEntity`-Import wurde auf den aktuellen Home-Assistant-Pfad umgestellt.

### Changed
- Version in `manifest.json` auf `0.3.10` angehoben.

## [0.3.9] - 2026-07-21

### Fixed
- `Meine Rückmeldung` wertet `feedback` nur aus, wenn der persönliche Eintrag den API-Status `RESPONDED` besitzt.
- `UNAVAILABLE`, `TIMEDOUT`, fehlende Rückmeldungen und nicht eindeutig zuordenbare Einträge bleiben neutral als `unbekannt`; `feedback: false` allein wird nicht mehr als negative Rückmeldung interpretiert.
- Ein erfolgreicher Feedback-POST setzt keinen lokalen Bestätigungsstatus mehr. Die Buttonfarbe wird ausschließlich aus dem anschließend vollständig von GroupAlarm gelesenen Alarmdatensatz ermittelt.
- Persönliche Rückmeldungen bleiben an die aktuelle Alarm-ID gebunden und werden nicht auf einen neuen Alarm übertragen.
- `alarm.endDate` wird als Ende der Rückmeldefrist für Zeitstempel, Countdown und Friststatus verwendet.
- Event-Endzeiten und geplante Event-Endzeiten werden nicht mehr fälschlich als Rückmeldefrist verwendet.

### Changed
- Version in `manifest.json` auf `0.3.9` angehoben.

## [0.3.8] - 2026-07-03

### Fixed
- `Aktive Alarmierung` bleibt bei laufendem Alarm aktiv, auch wenn keine Rückmeldefrist vorhanden oder diese bereits abgelaufen ist.
- Die aktive Alarmierung wird nicht mehr aus `scheduledEndtime`/Rückmeldefrist abgeleitet, sondern aus vorhandenem Alarm und echtem Alarm-/Event-Ende.
- `Meine Rückmeldung` wertet nur noch die Rückmeldung des konfigurierten Benutzers aus. Fremde negative oder positive Rückmeldungen beeinflussen den persönlichen Status nicht mehr.
- Neue Alarme starten ohne bestätigte eigene Rückmeldung neutral mit `offen`.
- Bestätigte Button-Farben werden weiterhin erst nach erfolgreicher Server-Antwort gesetzt.

### Changed
- Rückmeldefrist-/Countdown-Sensoren bleiben reine Informationssensoren und steuern nicht mehr die Sichtbarkeit des Einsatzes.
- Version in `manifest.json` auf `0.3.8` angehoben.


## [0.3.7] - 2026-06-19

### Added
- Added `dashboard_templates/wall_display_card.yaml` as a ready-to-copy Lovelace wall display template.
- Template includes alarm header, unit feedback counters, feedback deadline, personal feedback buttons, location and map.
- Template uses a single placeholder `__GA_PREFIX__` that can be replaced once for each organization/entity prefix.

### Changed
- Updated README with dashboard template usage instructions.


## [0.3.6] - 2026-06-19

### Fixed
- Rückmeldefrist/Countdown lädt jetzt den vollständigen Alarm per `GET /alarm/{alarmID}?update_for_user=true`, weil der Listen-Endpunkt nicht immer alle Zeit- und Rückmeldedetails enthält.
- Rückmeldefrist nutzt zusätzliche Fallback-Felder (`event.endDate`, `event.scheduledEndtime`, `scheduledEndTime`, `scheduledEndtime`).
- `Aktive Alarmierung` ist bei fehlender/unklarer Rückmeldefrist nicht mehr automatisch aktiv.

### Added
- Neuer Sensor `Alarmzeitpunkt` als direkt lesbarer Zeitstempel für Dashboard-Karten.

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
