# GroupAlarm fixtures

Only structurally preserved, anonymized GroupAlarm payloads may be stored here.
Create them with `scripts/anonymize_fixture.py` and review the result manually
before committing it.

Every JSON fixture must contain this top-level marker:

```json
{
  "_fixture_metadata": {
    "anonymized": true,
    "source": "groupalarm"
  }
}
```

No real payload has been added yet. Activity uses the separately reviewed
top-level `alarm.endDate` transition and the documented `event.abort` object;
an anonymized abort fixture is still required by Issue #7. Location uses the
separately reviewed top-level `optionalContent` address and WGS84 coordinates;
an anonymized missing-location fixture is still required by Issue #7. Feedback
eligibility and the local deadline use minimal synthetic structures matching
the separately reviewed `WAITING`/`TIMEDOUT` and timeout responses; raw
responses are never committed.
