# GroupAlarm API contract for v0.5.1

Status: Phase 0 contract, audited 2026-07-27

This is the allow-list for API operations and raw fields used by the rewrite.
Anything not listed here needs new official evidence or an anonymized real
fixture and a contract update before production use.

## Transport and authentication

- Origin: `https://app.groupalarm.com`
- API root: `/api/v1`
- App service root: `/api/v1/app`
- Authentication header: `Personal-Access-Token: <PAT>`
- Request and response media type: `application/json`
- Home Assistant's shared `aiohttp.ClientSession` will be used.
- No URL, header, body or response containing a token or personal/alarm data is
  logged.
- Every request has a finite timeout.
- JSON content type, top-level type and required consumed fields are validated
  before data reaches the domain mapper.

The Swagger documents also advertise organization-scoped `API-TOKEN`
authentication. It is not used because the integration is configured as a
specific user and needs the current user's personal feedback.

## Read operations

### Current user

`GET /api/v1/user/`

No parameters.

Consumed response fields:

| JSON path | Type | Meaning/use |
|---|---|---|
| `id` | integer | Stable current-user identity; required |
| `active` | boolean | Account status; informational until real behavior is verified |
| `name`, `surname`, `email` | string | Config-flow display only; never diagnostics/logging |

The response also documents session token fields. They are neither retained
nor exposed.

### Accessible organizations

`GET /api/v1/organizations`

No parameters. The response is an array of `Organization`.

Consumed response fields:

| JSON path | Type | Meaning/use |
|---|---|---|
| `[].id` | integer | Stable organization identity; required |
| `[].name` | string | User-facing selection/device name |
| `[].timezone` | string | Optional IANA timezone context |
| `[].state` | schema object | Not assigned domain semantics until its values are evidenced |

`?all=true` and the trailing-slash variant used by v0.3.10 are not part of the
documented operation.

### Alarm list gate

`GET /api/v1/alarms?organization={organizationID}&limit={limit}&offset={offset}`

Parameters:

| Parameter | Required | Contract |
|---|---:|---|
| `organization` | yes | integer organization ID |
| `type` | no | `all` or `own` |
| `limit` | no | integer `1..50`, default `10` |
| `offset` | no | integer, default `0` |
| `event` | no | integer event ID |

Response: object `AlarmList` with:

- `alarms`: array of `Alarm`
- `totalAlarms`: integer
- `strength`: strength map

Consumed lightweight change fields from each candidate alarm:

- `id`
- `organizationID`
- `startDate`
- `endDate`
- `event.id`
- `event.endDate`
- `event.archived`
- `event.abort`
- `feedbackQuantity`

No ordering or sort parameter is documented. `limit=1` therefore reduces
traffic but does not contractually mean “latest”. No ID-only, ETag,
`Last-Modified` or equivalent change endpoint is documented.

### Alarm detail

`GET /api/v1/alarm/{alarmID}?update_for_user=true`

Parameters:

| Parameter | Required | Contract |
|---|---:|---|
| `alarmID` | yes | positive integer path parameter |
| `update_for_user` | no | boolean; `true` requests user-adjusted data |

The response is `Alarm`. Fields consumed by the normalizer may include:

| JSON path | Type | Proven meaning |
|---|---|---|
| `id` | integer ≥ 1 | Alarm ID |
| `organizationID` | integer | Owning organization |
| `message` | string | Alarm message |
| `startDate` | date-time | Alarm start |
| `endDate` | date-time | Alarm close, not feedback deadline |
| `event.id` | integer | Event ID |
| `event.name` | string | Event/user-given name |
| `event.startDate` | date-time | Event start |
| `event.endDate` | date-time | Event close |
| `event.scheduledEndtime` | date-time | Scheduled event close, not feedback deadline |
| `event.archived` | boolean | Event archive flag |
| `event.abort` | object | Its presence proves that the alarm is no longer active |
| `optionalContent` | untyped | Optional address and WGS84 location source |
| `feedback[]` | array | Per-recipient feedback records |
| `feedbackQuantity.positive` | integer | Positive aggregate count |
| `feedbackQuantity.negative` | integer | Negative aggregate count |
| `feedbackQuantity.unknown` | integer | Unknown aggregate count |

Only a `feedback[]` item whose `alarmID` equals the current alarm and whose
`userID` equals the current user can determine personal feedback:

| `state` | `feedback` | Domain result |
|---|---|---|
| `RESPONDED` | `true` (boolean) | `komme` |
| `RESPONDED` | `false` (boolean) | `komme_nicht` |
| any other value | any value | `unbekannt` |
| `RESPONDED` | missing/non-boolean | `unbekannt` |

The Swagger schema does not enumerate `state`; `RESPONDED`, `TIMEDOUT` and
`UNAVAILABLE` are accepted because repository Issues #2/#20 record them from
real payloads. New values remain unknown until evidenced.

Alarm activity is mapped independently of recipient feedback: a validated
detail without top-level `endDate` and without `event.abort` is active. A
top-level `endDate` or the presence of `event.abort` makes it inactive. Event
close/archive fields and feedback/deadline state do not affect this axis.

Location consumes only `optionalContent.address`,
`optionalContent.coordinateFormat`, `optionalContent.latitude` and
`optionalContent.longitude`. The coordinate format may be absent (the documented
default) or exactly `WGS84`. Latitude and longitude may be finite numbers or
numeric strings within WGS84 ranges; both are required. Address is optional and
does not make invalid or missing coordinates usable. Legacy nested location
paths are not accepted.

For the same matching `RESPONDED` record, `userDuration` is the documented
traffic duration to the organization in minutes. It is consumed only to
confirm whether an explicitly requested arrival duration reached canonical
detail. It does not influence personal feedback, activity, eligibility or a
deadline.

### Organization feedback timeout

`GET /api/v1/messaging/timeout/{organizationID}`

Response:

```json
{
  "timeout": 300
}
```

`timeout` is an integer `10..86400` seconds. Its documented meaning is the
duration after which a notified user times out and cannot answer an alarm.
The specification does not identify the absolute server-side reference
timestamp. The integration therefore uses the product-defined local contract:
after a new alarm ID is detected, normalize canonical detail first. Load the
value once and calculate a Home-Assistant-local cutoff from detection time only
when the matching personal state is `WAITING` and the alarm is neither closed
nor aborted.

### App devices

`GET /api/v1/app/device?owner_id={userID}`

Parameters:

| Parameter | Required | Contract |
|---|---:|---|
| `owner_id` | yes | queried user's integer ID |
| `organization_id` | no | unnecessary for a user querying their own resources |

The response is an array of `Device` and includes sensitive `pushToken`.
Immediately reduce each item to:

- `id`
- `name`
- `active`
- `isMainDevice`

Never retain, log, diagnose or expose `pushToken`, OS details or other fields
not needed for explicit device selection. Do not automatically select a device
when the user has not done so.

## Write operations

### Standard personal feedback

`POST /api/v1/messaging/feedback`

Body for this integration:

```json
{
  "alarmID": 1234567,
  "organizationID": 123456,
  "response": true,
  "userID": 123456
}
```

`response` and `userID` are schema-required. The request model allows alarm or
organization scope; this integration always sends both current alarm and
organization IDs to constrain the action.

The operation documents `200`, `400`, `403` and `500`. A `200` means the POST
was accepted; it does not optimistically change Home Assistant state. The
detail GET must confirm the same alarm, same user and `RESPONDED`.

### Positive feedback with arrival duration

`POST /api/v1/app/feedback`

Body:

```json
{
  "alarmID": 1234567,
  "deviceID": 123456,
  "response": true,
  "answerData": {
    "duration": 5
  }
}
```

- `alarmID` and `deviceID` are required by the schema.
- `response` is sent explicitly as boolean `true`.
- `answerData.duration` is an integer number of minutes in traffic to the
  organization.
- `answerData.distance` is documented but not used.
- Negative feedback never uses this endpoint or sends `answerData`.

The schema defines no duration limits. The planned UI range `1..180` therefore
remains an integration validation choice and must be documented as such.

## Error contract

Response bodies are never copied unfiltered into logs or user-facing
exceptions.

| Condition | Client exception | Home Assistant handling |
|---|---|---|
| `401` | `ApiAuthenticationError` | Config-entry auth failure/reauth |
| `403` while validating PAT | `ApiAuthenticationError` or explicit permission subtype | Reauth only if the token itself is rejected; otherwise permission error |
| `403` for organization/action | `ApiPermissionError` | Isolate affected organization/action |
| `404`, `409`, `422` or other validated domain `4xx` | `ApiRequestRejectedError` | Safe translated action/setup error |
| `429` | `ApiRateLimitError(retry_after)` | Back off; honor valid `Retry-After` |
| `5xx` | `ApiServerError` | Temporary update/setup failure |
| timeout, DNS, connection loss | `ApiTransportError(outcome_unknown=...)` | Temporary failure; never blind fallback after a write |
| invalid content type/JSON/top-level shape | `ApiProtocolError` | Temporary/API compatibility failure |
| missing or invalid consumed fields | `ApiPayloadError` | Organization-scoped where possible |

Whether an action-specific `403` means authentication or authorization must be
decided from operation context, not status code alone.

## Traffic-minimizing polling contract

The design goal is to avoid downloading alarm detail on every poll.

1. Load the current user once per config-entry setup/reload.
2. Load accessible organizations during setup/options/reconfigure, not every
   alarm poll.
3. Load the organization timeout once for each newly detected alarm ID whose
   canonical detail proves an open personal `WAITING` state.
4. Poll the alarm-list gate once per configured interval and organization,
   with bounded parallelism.
5. Cache the selected alarm ID and a small list-derived revision fingerprint.
6. Fetch alarm detail only when:
   - a new alarm ID is discovered;
   - the list-derived fingerprint changes for the same alarm;
   - the user sends feedback and reconciliation is required;
   - recovery from an error requires canonical state; or
   - a conservative safety refresh is due.
7. Do not issue API calls for local countdown ticks.

The revision fingerprint is made only from documented lightweight fields, not
a hash of the complete sensitive payload. It detects close/archive/aggregate
changes at the same alarm ID without storing raw list bodies.

This design is conditional on proving how to select the newest relevant alarm.
Until ordering is evidenced, using `limit=1` alone is unsafe. Phase 2 must
choose one of these evidence-backed variants:

- confirm newest-first behavior with real fixtures and record it as observed,
  with a periodic wider safety scan; or
- request a bounded page and select the candidate deterministically from
  validated `startDate` plus ID, accepting the extra list traffic.

No currently documented endpoint permits a correct ID-only poll. This is an
explicit API limitation, not a reason to guess.

### Phase 2 implementation policy

The initial implementation uses one `limit=10, offset=0` gate request per
configured organization and polling interval. It validates every returned
candidate and selects the maximum `(startDate, id)` pair within that bounded
page. Ten entries are a deliberate compromise: the response remains small,
while out-of-order entries inside the first page do not make `limit=1` choose
the wrong candidate.

This does **not** turn the undocumented server ordering into a guarantee. If
an organization has more than ten alarms, the API contract still cannot prove
that the newest alarm is present in the first page. Real list fixtures are
still required to establish the observed ordering policy.

After initial detail loading, unchanged alarm ID and revision reuse the
normalized canonical detail. A detail request is made only for:

- a new selected alarm ID;
- a changed documented list fingerprint for the same ID; or
- a safety refresh after 15 minutes.

The setup path loads the user and accessible organizations once per config
entry. Organization names are refreshed there, not during alarm polling.
`DataUpdateCoordinator(always_update=False)` suppresses entity callbacks when
the immutable normalized snapshots compare equal.

For a new alarm ID, canonical detail is normalized before the organization
timeout is requested. The timeout is skipped for answered, timed-out,
unavailable, closed, aborted or otherwise non-`WAITING` alarms and is not
refreshed for ordinary list polls or local countdown ticks.

## Feedback delivery and reconciliation

Each alarm/organization has one asynchronous, non-queuing send lock. A second
press is rejected instead of waiting to issue a later duplicate POST.

1. Validate current alarm identity and proven feedback eligibility.
2. Send standard feedback, or positive duration feedback when configured.
3. On an explicit app request rejection that guarantees non-acceptance, use
   the standard endpoint as the documented duration fallback.
4. On timeout or connection loss, GET detail first. If the intended response is
   confirmed, do not POST again. If still unknown, keep the state unknown and
   do not risk a blind duplicate.
5. After any accepted POST, perform a short bounded detail reconciliation.
6. Change personal state only on a matching server-confirmed GET record.

Phase 3 performs at most three detail GETs: immediately, after one second and
after two further seconds. An accepted or transport-ambiguous write that
remains unconfirmed is retained as pending. Its buttons stay disabled and the
regular low-traffic poll temporarily forces one canonical detail GET per poll
until the same response is confirmed or a new alarm replaces the target.

The app endpoint falls back to standard feedback only for a sanitized
`GroupAlarmRequestError`, representing an explicit HTTP request rejection.
Transport failures and `5xx` responses reconcile first and never trigger a
second POST while the first outcome is unknown. A confirmed response with a
missing or different `userDuration` also does not trigger a fallback; the user
is informed that duration delivery could not be verified.

## Blocked semantics

The contract does not yet prove:

- the absolute server-side personal feedback deadline;
- the server's notification/reference timestamp;
- newest-first list order;
- idempotency of either feedback POST;
- the complete set of unambiguous app-feedback rejection responses.

The local cutoff must not be presented as that unknown server timestamp.

## Diagnostics and repair boundary

Diagnostics never serialize config-entry data, client internals, raw API
payloads or content-bearing domain fields. Real user, organization, alarm and
event IDs are transformed into deterministic, config-entry-local SHA-256
pseudonyms. Output is restricted to integration/configuration metadata, last
successful update time, organization-scoped error classes, state flags and
recognized JSON field paths without their values.

The only Phase 5 repair issue is created when at least one arrival duration is
stored without a positive integer app-device ID. This is actionable through
the existing Options Flow. Unknown alarm semantics, API ordering, transport
failures and missing real fixtures do not create repairs because a user cannot
correct those conditions.
