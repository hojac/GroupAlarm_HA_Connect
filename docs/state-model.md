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
axis. The organization timeout describes a duration but cannot decide this
state until its reference timestamp is proven.

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
| Known active | `known_active` | A proven absolute deadline is in the future and no personal answer is confirmed |
| Known expired | `known_expired` | A proven absolute deadline passed without a confirmed answer |
| Answered | `answered` | Personal feedback is server-confirmed |
| Unknown | `unknown` | No proven absolute deadline |

The initial mapper intentionally emits only `no_alarm`, `answered` and
`unknown`. `known_active`/`known_expired` are blocked until the deadline field
and reference timestamp are evidenced by current real payloads.

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
3. Load/cache organization timeout.
4. Load a sufficiently safe alarm-list window.
5. Select a validated candidate only under the ordering policy documented in
   `api-contract.md`.
6. Fetch detail for that candidate.
7. Normalize and publish one snapshot per organization.

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

### Feedback transition

| Event | Before | Immediate local result | Confirmed result |
|---|---|---|---|
| Positive/negative button pressed | eligibility `open`, no send lock | Acquire lock; personal feedback unchanged | Matching GET selects `komme` or `komme_nicht` |
| POST accepted but GET not yet updated | any unconfirmed personal state | Remain `unknown`; bounded reconciliation | Update only when `RESPONDED` appears |
| POST transport outcome unknown | any | No blind second POST; fetch canonical detail | Confirm, or remain `unknown` with error |
| New alarm ID arrives during reconciliation | old alarm pending | Discard old personal state/result | Reconcile only the new alarm independently |

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

No timer implementation is allowed until the blocked deadline mapping is
resolved.

## Location

Location normalization is optional:

- accept only fixture-proven JSON paths;
- parse latitude/longitude as finite numbers in valid ranges;
- require both coordinates before exposing a GPS position;
- never invent `0,0` or reuse stale coordinates for a new alarm;
- allow address and coordinates to be absent;
- do not include raw address, coordinates or alarm content in diagnostics.

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

## Planned typed components

- Frozen enums/dataclasses for every state above.
- `GroupAlarmClient`: asynchronous transport and defensive payload validation.
- Pure list/detail/feedback/location mappers.
- Config-entry runtime data containing one client, one coordinator and
  lifecycle-owned resources.
- One coordinator with bounded per-organization concurrency.
- Entity descriptions and entities that only project normalized values.
- Per-alarm/organization feedback locks.
- One optional countdown ticker registry per config entry.

## Implementation phases and gates

| Phase | Scope | Gate |
|---|---|---|
| 0 | Sources, contracts, state model, anonymizer | Documents reviewed; no guessed semantics |
| 1 | Project foundation, typed client, config flow, migration, translations | Client/config-flow tests, lint and typing pass |
| 2 | Coordinator, multiple organizations, normalization, read-only entities, low-traffic list gate | Lifecycle, isolation and polling tests pass |
| 3 | Server-confirmed feedback, buttons, arrival duration, safe reconciliation/fallback | No optimistic state or blind duplicate POST |
| 4 | Deadline and countdown | Only after real field/path/reference-time evidence and fixtures |
| 5 | Diagnostics, repairs, CI, docs/dashboard, coverage | Full validation and ≥95% meaningful coverage |
| 6 | Real HA test, upgrade/migration test, release candidate | Separate approval before merge, tag or release |

Phase 4 is intentionally independent. Missing deadline evidence does not block
the foundation, reading, traffic optimization or feedback reconciliation, but
it does block button enablement where eligibility cannot otherwise be proven.
