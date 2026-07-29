# Domain state model for v0.5.0

Status: Phase 0 design, audited 2026-07-27

Home Assistant entities consume an immutable normalized domain model. They do
not parse GroupAlarm JSON. All mapping functions are pure and typed; I/O,
normalization and presentation are separate layers.

## Organization snapshot

Each configured organization has an independent snapshot:

```text
OrganizationSnapshot
├── organization identity and display metadata
├── availability/error state
├── selected alarm reference
├── normalized alarm (optional)
├── alarm visibility
├── alarm activity
├── feedback eligibility
├── personal feedback
├── feedback deadline
├── aggregate feedback counts
└── normalized location (optional)
```

Snapshots from successful organizations remain usable when another
organization fails. A confirmed global PAT failure affects the config entry;
organization-specific permission, protocol or payload failures affect only
that organization.

## Independent state axes

These axes must never supply default values for one another.

### Alarm visibility

| State | Meaning |
|---|---|
| `NO_ALARM` | No validated alarm has been loaded |
| `VISIBLE` | A validated alarm is retained for display |

Visibility says nothing about activity, feedback eligibility or deadline. The
last alarm may remain visible after close, abort or timeout.

### Alarm activity

| State | Meaning |
|---|---|
| `ACTIVE` | A documented/fixture-proven alarm or event status proves activity |
| `INACTIVE` | A documented/fixture-proven status proves close/abort/inactivity |
| `UNKNOWN` | Available fields do not prove either state |

An alarm message, alarm existence, future timestamp or running countdown is not
an activity signal. The exact active/inactive mapper remains blocked until
real list/detail fixtures prove the status shape, including `event.abort`.

### Feedback eligibility

| State | Stable value | Meaning |
|---|---|---|
| Open | `open` | GroupAlarm is proven to accept feedback for this user/alarm |
| Closed | `closed` | GroupAlarm is proven not to accept feedback |
| Unknown | `unknown` | Current evidence cannot decide |

Buttons require `open`; `unknown` is fail-safe and does not enable them. Alarm
visibility, activity and personal response must not be substituted for this
axis. A matching `WAITING` record yields `open`; matching `RESPONDED`,
`TIMEDOUT` or `UNAVAILABLE` records yield `closed`. The organization timeout
adds a separate local cutoff and cannot open an otherwise unknown state.

### Personal feedback

| State | Stable value | Derivation |
|---|---|---|
| No alarm | `no_alarm` | No current validated alarm |
| Unknown | `unknown` | Alarm exists, but no matching confirmed answer |
| Positive | `komme` | Current alarm/current user item has `state == "RESPONDED"` and boolean `feedback is true` |
| Negative | `komme_nicht` | Current alarm/current user item has `state == "RESPONDED"` and boolean `feedback is false` |

`UNAVAILABLE`, `TIMEDOUT`, missing items, other users, other alarm IDs and
non-boolean feedback stay `unknown`. A new alarm ID immediately discards the
previous personal state. A successful POST does not update this axis; only the
following canonical GET can.

### Feedback deadline

| State | Stable value | Meaning |
|---|---|---|
| No alarm | `no_alarm` | No current alarm |
| Known active | `known_active` | The local detection-based deadline is in the future and no personal answer is confirmed |
| Known expired | `known_expired` | The local detection-based deadline passed without a confirmed answer |
| Answered | `answered` | Personal feedback is server-confirmed |
| Unknown | `unknown` | No proven absolute deadline |

The payload mapper emits `answered` or `unknown`. The coordinator adds
`known_active` and `known_expired` from the new-alarm detection time plus the
validated organization timeout. This is intentionally not a claim about the
unknown GroupAlarm server-side reference timestamp.

Forbidden deadline inputs:

- `alarm.endDate` (alarm close)
- `event.endDate` (event close)
- `event.scheduledEndtime` (scheduled event close)
- any unqualified `scheduledEndTime`/`scheduledEndtime`
- arrival duration/time
- undocumented lookalikes such as `feedbackDeadline`,
  `feedbackEndDate` or `answerDeadline`

## Core identities and replacement rules

- User ID and organization ID are validated positive integers.
- Alarm ID is a validated positive integer.
- The current alarm belongs to the snapshot's organization.
- Detail `id` and `organizationID` must match the requested alarm and
  organization. A mismatch is a payload error, not data to merge.
- A new selected alarm ID creates a new normalized alarm value. State from the
  previous ID is not copied.
- List and detail data are mapped explicitly. Detail is canonical for personal
  feedback; no flat dictionary merge is allowed.
- Entity/config unique IDs are based on stable domain identities, never token
  hashes or mutable names.

## Polling and state transitions

### Initial load

1. Load user identity once.
2. Resolve configured organization identities.
3. Load a sufficiently safe alarm-list window.
4. Select a validated candidate only under the ordering policy documented in
   `api-contract.md`.
5. For a newly detected alarm ID, fetch canonical detail and the organization
   timeout together.
6. Normalize and publish one snapshot per organization.

### Regular low-traffic poll

1. Request only the alarm-list gate.
2. Compare selected alarm ID and a documented list-derived revision
   fingerprint with the cached reference.
3. If neither changed and no safety refresh is due, reuse canonical detail.
4. If ID or revision changed, fetch and normalize detail.
5. Publish only changed immutable snapshots; coordinator equality suppresses
   unnecessary entity callbacks.

This handles a new alarm by ID while still detecting close/aggregate changes
at the same ID. It does not claim that `limit=1` is safe before list ordering is
proven.

Phase 2 implements this with a bounded ten-entry list page and a 15-minute
canonical-detail safety refresh. The selector is deterministic within the
page, but the first page is not claimed to contain the globally newest alarm
until real payloads prove server ordering.

### Feedback transition

| Event | Before | Immediate local result | Confirmed result |
|---|---|---|---|
| Positive/negative button pressed | eligibility `open`, no send lock | Acquire lock; personal feedback unchanged | Matching GET selects `komme` or `komme_nicht` |
| POST accepted but GET not yet updated | any unconfirmed personal state | Remain `unknown`; bounded reconciliation | Update only when `RESPONDED` appears |
| POST transport outcome unknown | any | No blind second POST; fetch canonical detail | Confirm, or remain `unknown` with error |
| New alarm ID arrives during reconciliation | old alarm pending | Discard old personal state/result | Reconcile only the new alarm independently |

Phase 3 uses one non-queuing asynchronous lock per alarm/organization. It runs
at most three reconciliation GETs with delays `0`, `1` and `2` seconds.
Unconfirmed writes remain pending and force canonical detail on the normal
polling cadence; this blocks another button press without creating aggressive
polling. A new alarm ID discards pending state for the old target.

An explicitly rejected app-duration request may fall back once to standard
positive feedback. Timeout, connection loss and `5xx` never cause an immediate
second POST. Canonical `feedback[].userDuration` can confirm the requested
duration, but a missing duration never weakens a confirmed personal response
and never licenses another POST.

## Countdown lifecycle

The local ticker is separate from API polling and owned once per config entry.

- Start only for `known_active`.
- Tick locally without an API request.
- Stop and remove the timer on `answered`, `known_expired`, `unknown`,
  `no_alarm`, alarm replacement, reload or unload.
- Emit “Rückmeldung erhalten” for `answered`, “abgelaufen” for
  `known_expired`, “unbekannt” for `unknown`, and “kein Alarm” for
  `no_alarm`.
- Never generate second-by-second writes without a known running deadline.
- Document a recorder exclusion for the countdown entity if second-level
  history is not useful.
- Reject feedback dynamically at the deadline even if an entity update is
  delayed.

## Location

Location normalization is optional:

- accept only fixture-proven JSON paths;
- parse latitude/longitude as finite numbers in valid ranges;
- require both coordinates before exposing a GPS position;
- never invent `0,0` or reuse stale coordinates for a new alarm;
- allow address and coordinates to be absent;
- do not include raw address, coordinates or alarm content in diagnostics.

Phase 2 creates the location tracker identity but keeps it unavailable. The
official `optionalContent` schema is untyped and no anonymized real location
fixture has yet proven its JSON paths. The legacy integration's fallback paths
are therefore not copied into the normalizer.

## Implemented Phase 3 entity model

The implemented read-only entity set currently exposes alarm ID, message,
start timestamp, compatibility alarm time, event name, aggregate feedback
counts, server-confirmed personal feedback, and a disabled-by-default user-ID
diagnostic sensor. Activity remains an unknown binary-sensor state, and the
location tracker remains unavailable, until their source mappings are proven.

Phase 3 adds translated positive and negative button entities, server-confirmed
reconciliation, optional arrival-duration delivery, pending-write protection
and safe fallback notifications. A matching `WAITING` record opens feedback
only while the coordinator's local countdown is greater than zero.

Phase 4 adds deadline-end, deadline-status and countdown entities. The single
local ticker is owned by the config-entry coordinator and is removed after
answer, expiry, alarm replacement, reload or unload.

## Availability and error model

| Scope | Example | Result |
|---|---|---|
| Config entry | confirmed invalid PAT | Reauth; all snapshots unavailable |
| Organization | permission/payload failure for one organization | Only that organization's entities unavailable |
| Temporary transport/server failure | timeout or `5xx` | Preserve last state where HA conventions allow; mark update failure |
| Rate limit | `429` | Respect `Retry-After`; no aggressive retry |
| Recovery | next validated success | Clear only the affected error and publish fresh state |

Log once on transition into an unavailable state and once on recovery. Do not
log raw payloads or repeat the same failure every poll.

## Typed components

- Frozen enums/dataclasses for every state above.
- `GroupAlarmClient`: asynchronous transport and defensive payload validation.
- Pure list/detail/feedback/location mappers.
- Config-entry runtime data containing one client, one coordinator and
  lifecycle-owned resources.
- One coordinator with bounded per-organization concurrency.
- Entity descriptions and entities that only project normalized values.
- Per-alarm/organization feedback locks and pending-write reconciliation.
- One optional countdown ticker registry per config entry.

## Implementation phases and gates

| Phase | Scope | Gate |
|---|---|---|
| 0 | Sources, contracts, state model, anonymizer | Documents reviewed; no guessed semantics |
| 1 | Project foundation, typed client, config flow, migration, translations | Client/config-flow tests, lint and typing pass |
| 2 | Coordinator, multiple organizations, normalization, read-only entities, low-traffic list gate | Lifecycle, isolation and polling tests pass |
| 3 | Server-confirmed feedback, buttons, arrival duration, safe reconciliation/fallback | No optimistic state or blind duplicate POST |
| 4 | Local deadline and countdown | Timeout endpoint, matching feedback state and local detection reference are tested |
| 5 | Diagnostics, repairs, CI, docs/dashboard, coverage | Full validation and ≥95% meaningful coverage |
| 6 | Real HA test, upgrade/migration test, release candidate | Separate approval before merge, tag or release |

The local deadline is deliberately independent of the unknown server-side
notification timestamp. Missing server timing evidence does not block the
local safety cutoff.

## Diagnostic projection

Diagnostics are a separate projection of the normalized state. They retain
only:

- pseudonymized identities;
- availability and error class;
- alarm/location presence flags;
- activity, eligibility, personal-feedback and deadline enums;
- last successful coordinator update;
- recognized field paths without values.

They never reuse entity values for alarm message, organization name, address,
coordinates or numeric IDs. Pseudonyms are stable inside one Config Entry but
different across Config Entries, preventing a global cross-entry identifier.
