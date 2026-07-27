# Source audit for the v0.5.0 rewrite

Audit date: 2026-07-27

This document records the sources used before production code is written on
`rewrite/v0.5.0`. The source order and stop rules from the project brief remain
binding: a convenient field name is not evidence of domain semantics.

## Source inventory

### Local project sources

| Source | Integrity and date | Scope | Result |
|---|---|---|---|
| `groupalarm-api-docs.json` | 986,874 bytes; SHA-256 `ee2ba9806f483cf80bd5177d05bc23ce7d1ede91861f3f18704bc5818d2ec8a7`; metadata `downloaded_at: 2026-07-27` | Aggregated GroupAlarm Swagger 2.0 specifications | Valid JSON; completely parsed |
| `GroupAlarm_HA_Neubau_Masterprompt.md` | 38,699 bytes; 835 lines; SHA-256 `b8752291b81a64187809d47c7add717f055e9d89476fab50261df542f83a956a` | Requirements, source priority, stop rules and acceptance criteria | Completely reviewed |

No additional PDF specification was supplied. PDFs are optional and are not a
Phase 0 blocker.

The API bundle contains 26 services, 317 paths, 496 operations, 360
definitions and 700 local `$ref` occurrences. All local references resolve.
The contained service areas are:

`alarming`, `app`, `appointment`, `audit`, `billing`, `call`, `connection`,
`dwd-warn`, `email`, `first-responder`, `flow`, `instruction`, `journal`,
`messaging`, `chat`, `monitor`, `organization`, `pager`, `quota`, `rbac`,
`sms`, `shop`, `storage`, `support`, `things`, and `user`.

All five services required by this integration are present.

| Service | Swagger `info.version` | Paths | Definitions |
|---|---|---:|---:|
| `alarming` | `07c482699a50b45ca9db315ebb203bca63c00008` | 81 | 85 |
| `messaging` | `02a9376572ec971858ab15c7290ffa9aa45189ac` | 7 | 8 |
| `app` | `02a9376572ec971858ab15c7290ffa9aa45189ac` | 13 | 7 |
| `organization` | `02a9376572ec971858ab15c7290ffa9aa45189ac` | 17 | 14 |
| `user` | `02a9376572ec971858ab15c7290ffa9aa45189ac` | 27 | 36 |

The bundle identifies `https://developer.groupalarm.com/` as its source index
and records the individual official JSON URL for every service.

### Current official GroupAlarm specifications

The five required JSON specifications were downloaded again on 2026-07-27 and
parsed. Each current document is JSON-structurally identical to its service
object in the local bundle.

| Official source | Download SHA-256 | Equal to bundled service |
|---|---|---|
| [Alarming](https://developer.groupalarm.com/api/alarming.json) | `53d942b57e495542fec9cd3556c23d4704234916d869cd37c2b2950b53b0b85a` | yes |
| [Messaging](https://developer.groupalarm.com/api/messaging.json) | `1b2b2cd44426dc1f23bf9ed42ae102eef2e0d96515bfc3f6302ee9dd70b1cdc2` | yes |
| [App](https://developer.groupalarm.com/api/app.json) | `d14a3725b1f60c3aca6335d449ddb2f17cf21a1a0735ea3662479a6028ce0d3e` | yes |
| [Organization](https://developer.groupalarm.com/api/organization.json) | `e2a8ba9f3f77ccc503bd85cd9343ca2ae26b6d5856171f43486eee4b37fdea96` | yes |
| [User](https://developer.groupalarm.com/api/user.json) | `f2604c8363dfbee26ff6683e541ea7b2c03555d4b660291b5f2e4ac1c58c4a94` | yes |

The public [GroupAlarm REST API overview](https://www.groupalarm.com/en/features/rest-api/)
was treated as supplementary prose. Its feedback example uses an
organization-scoped `API-TOKEN`; this integration requires a user-scoped
Personal Access Token and therefore uses the `Personal-Access-Token` header
documented by the Swagger specifications.

### Home Assistant and HACS

Current official guidance reviewed for the planned implementation:

- [Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/)
- [Fetching data and `DataUpdateCoordinator`](https://developers.home-assistant.io/docs/integration_fetching_data/)
- [Config entries](https://developers.home-assistant.io/docs/config_entries_index/)
- [Config flow](https://developers.home-assistant.io/docs/config_entries_config_flow_handler/)
- [Reauthentication](https://developers.home-assistant.io/docs/config_entries_config_flow_handler/#reauthentication)
- [Reconfigure](https://developers.home-assistant.io/docs/config_entries_config_flow_handler/#reconfigure)
- [Diagnostics](https://developers.home-assistant.io/docs/core/integration_diagnostics/)
- [Repairs](https://developers.home-assistant.io/docs/core/platform/repairs/)
- [HACS integration publication requirements](https://www.hacs.xyz/docs/publish/integration/)

The target remains a fully asynchronous cloud-polling custom integration with
typed `ConfigEntry.runtime_data`, coordinated data fetching, UI configuration,
reauthentication, reconfiguration, translations, diagnostics and automated
tests. `DataUpdateCoordinator(always_update=False)` is appropriate once the
normalized immutable state has correct equality semantics.

### Existing repository

Repository: [hojac/GroupAlarm_HA_Connect](https://github.com/hojac/GroupAlarm_HA_Connect)

- Audited baseline: `main` commit
  `152079041e31a1d53a638cf7e8e10e2da1ad2ba0`.
- Existing release version: `0.3.10`.
- Existing tests: ten small `unittest` tests; all passed during the initial
  read-only assessment.
- No real payload fixtures, Home Assistant test harness, lint configuration,
  type checking, coverage gate or effective CI workflow.
- `.gitignore` is absent.
- Nine `.pyc` files are still tracked even though Issue #15 states generated
  cache files are no longer part of the current repository.
- `.github/workflows` and `.github/ISSUE_TEMPLATE` are one-byte placeholder
  files rather than usable files/directories.
- UI strings are embedded in German in `strings.json`; English and German
  translation files are absent.
- Config entry version 2 exists without an `async_migrate_entry`
  implementation. Reauth and reconfigure are absent.
- The config-entry unique ID contains a token hash and is not stable across a
  token change.
- The current release tag is `v.0.3.10`, not the intended `v0.3.10` form.

The repository history, README, changelog, releases and Issues #1 through #20
were used as experience and regression sources, below the official API
specification in the required source ranking.

## Confirmed API coverage

The exact contracts intended for the rewrite are recorded in
[`api-contract.md`](api-contract.md). Phase 0 confirms that the source includes:

- `GET /api/v1/user/`
- `GET /api/v1/organizations`
- `GET /api/v1/alarms`
- `GET /api/v1/alarm/{alarmID}`
- `GET /api/v1/messaging/timeout/{organizationID}`
- `POST /api/v1/messaging/feedback`
- `GET /api/v1/app/device`
- `POST /api/v1/app/feedback`

The specification provides no dedicated alarm-ID-only change endpoint, no
documented sort parameter/order for `GET /alarms`, and no documented ETag or
`Last-Modified` contract. This constrains traffic optimization; see the
two-stage polling design in `api-contract.md`.

## Confirmed semantic facts

- `Alarm.id` is a positive integer alarm identifier.
- `Alarm.startDate` is when the alarm started.
- `Alarm.endDate` is explicitly “time, when alarm was closed”.
- `Event.endDate` is when the event was closed.
- `Event.scheduledEndtime` is when the event is scheduled to close.
- `Feedback.state` is a string with no enum in the Swagger schema.
- A personal answer is accepted only from a real payload entry for the current
  user and current alarm where `state == "RESPONDED"` and `feedback` is a
  boolean.
- `OrganizationTimeout.timeout` is the number of seconds after which a
  notified user times out and cannot answer. Its documented range is
  `10..86400`.
- `AnswerData.duration` is traffic duration to the organization in minutes.
- `Feedback.userDuration` is the canonical detail field for the user's traffic
  duration and may confirm a previously requested arrival duration.
- `Device` responses contain `pushToken`; the integration must immediately
  reduce those payloads to non-sensitive selection data.

## Contradictions and rejected assumptions

1. **Top-level `alarm.endDate` is not a deadline.** README, changelog and
   closed Issue #3 treat this as a feedback deadline. The current official
   schema defines it as the time the alarm was closed. The rewrite must not
   reuse the old interpretation.
2. **`event.scheduledEndtime` is not a feedback deadline.** The official schema
   defines that exact JSON path as the planned event close. Issue #20 describes
   an unqualified `scheduledEndtime`/`scheduledEndTime` as arrival time. Without
   its complete real JSON path it may be a different field; neither statement
   supports using it as a feedback deadline.
3. **Organization URL mismatch.** The old client calls
   `/organizations/?all=true`. The current official operation is
   `/organizations`, has no `all` parameter and returns all accessible
   organizations for the current user.
4. **Undocumented fallback fields.** The old mapper accepts
   `feedbackDeadline`, `feedbackEndDate`, `answerDeadline`, `selfFeedback`,
   `ownFeedback` and `myFeedback`. These are not supported by the audited
   specification or committed real fixtures and are excluded.
5. **Flat payload merge.** The old coordinator merges list and detail
   dictionaries. Conflicting nested fields can be silently hidden. The rewrite
   will use explicit normalization and field precedence.
6. **Unsafe fallback POST.** The old delivery helper falls back from app
   feedback for every duration-delivery exception. A timeout or connection
   loss has an unknown server outcome and can cause a duplicate answer. Only a
   clearly rejected request may fall back immediately; ambiguous outcomes
   require GET reconciliation first.
7. **Newest-alarm assumption.** `limit=1` reduces the response but does not
   prove which alarm is returned because the operation documents pagination,
   not ordering. Correctness cannot depend on undocumented ordering.

## Open questions and required real fixtures

The following questions are blocked until anonymized current payloads from the
same real alarm are available:

1. Which absolute timestamp, if any, is the personal feedback deadline?
2. Is `OrganizationTimeout.timeout` measured from `Alarm.startDate`, an
   individual notification timestamp, or another timestamp?
3. Which documented status or field proves that feedback remains allowed for
   a visible alarm?
4. What complete JSON path was meant by the arrival-related
   `scheduledEndtime` in Issue #20?
5. Does the production API reliably return `GET /alarms` newest-first despite
   the missing ordering contract?
6. Which exact app-feedback `4xx` responses guarantee that no answer was
   accepted and therefore permit an immediate messaging fallback?

Required anonymized cases are: new unanswered, positive answered, negative
answered, known active deadline, expired deadline, closed/aborted but visible,
missing location, missing deadline and a second organization. For each alarm,
capture the list form, detail form with `update_for_user=true`, organization
timeout response and the subsequent server-confirmed feedback state.

Use `scripts/anonymize_fixture.py` before committing any capture. The tool
removes token-bearing keys, deterministically pseudonymizes identifiers and
sensitive text/location fields, and scrubs obvious embedded email, phone and
JWT values. Its output still requires human review because arbitrary
free-form or previously unknown fields cannot be proven safe by key matching
alone.

## Phase 0 decision

The API and state foundation can proceed. Production implementation of the
deadline, countdown and feedback-button availability remains blocked. Those
states must stay explicitly unknown until the missing semantics are evidenced.

## Phase 5 platform-source refresh

The quality implementation was checked again on 2026-07-27 against current
official primary sources:

- [Home Assistant diagnostics rule](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/diagnostics/)
  requires useful diagnostics and explicit removal of passwords, tokens and
  coordinates.
- [Home Assistant repairs rule](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/repair-issues/)
  requires issues to be actionable instead of reporting conditions the user
  cannot fix.
- [Home Assistant repairs platform](https://developers.home-assistant.io/docs/core/platform/repairs/)
  documents issue identity, severity, persistence and translation contracts.
- [Home Assistant coverage rule](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/test-coverage/)
  keeps the target above 95 percent for all integration modules.
- [HACS integration requirements](https://www.hacs.xyz/docs/publish/integration/)
  confirm the one-integration repository layout, manifest metadata and local
  brand directory.
- [HACS validation action](https://www.hacs.xyz/docs/publish/action/)
  validates the same repository rules used by HACS and supports integration
  category checks on pushes and pull requests.
- [Official GroupAlarm PAT guide](https://docs.groupalarm.com/de/article/profil-sicherheit-15o21cd/)
  is the sole step-by-step PAT creation source linked from the README.

These sources led to content-reduced diagnostics, one narrowly actionable
invalid-device repair, pinned CI action revisions, an explicit repository
safety gate and corrected user documentation. Repository topics remain
external GitHub metadata; strict HACS validation will report their absence
until the repository owner adds the required Home Assistant topic.
