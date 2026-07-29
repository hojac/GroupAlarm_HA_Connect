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

No real payload has been added yet. Activity and location mappings therefore
remain blocked until the required anonymized evidence is available. Feedback
eligibility and the local deadline use minimal synthetic structures matching
the separately reviewed `WAITING`/`TIMEDOUT` and timeout responses; raw
responses are never committed.
