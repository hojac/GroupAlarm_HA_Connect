# Quality and release gates

This document records the reproducible checks for the `0.5.1` release.

## Local checks

```bash
uv sync --locked --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy custom_components/groupalarm_ha_connect
uv run pytest \
  --cov=custom_components/groupalarm_ha_connect \
  --cov-report=term-missing \
  --cov-fail-under=95
uv run python scripts/check_repository.py
```

The repository safety command operates on the tracked files plus unignored
untracked files that would be candidates for the next commit. It rejects Python
bytecode, tool caches, coverage output, local environment or Home Assistant
secret files, high-confidence credential formats and JSON fixtures without an
explicit anonymization marker.

## CI

`.github/workflows/ci.yml` runs:

- Ruff lint and format check;
- Mypy strict;
- Pytest with branch coverage and a 95 percent gate;
- the tracked-file repository safety check;
- Home Assistant Hassfest;
- HACS integration validation.

Every referenced action is pinned to an immutable full commit SHA. The workflow
also pins uv `0.11.29`, requests Python `3.14.2`, installs from `uv.lock`, uses
read-only repository permissions and cancels obsolete runs for the same ref.

## Diagnostics

`diagnostics.py` exports only pseudonymized identifiers and non-content state
metadata. Tests use deliberately recognizable tokens, names, free text, IDs,
addresses and coordinates, then verify that none survives serialization.

## Repairs

The invalid feedback-device repair is emitted only when an arrival duration
depends on a missing or malformed stored device ID. It is cleared automatically
after the Options Flow stores a valid ID or removes all durations.

No repair is emitted for unknown API semantics, missing fixtures, rate limits,
server outages or transport errors because those conditions are not directly
actionable by the user.

## External repository gate

The required GitHub topics are configured and the latest HACS repository
validation passed. Every release candidate must keep that validation green.

## Release boundary

Passing Phase 5 checks does not authorize a merge, tag or release. Phase 6 still
requires a real Home Assistant installation test, two organizations, feedback
with and without arrival duration, migration/upgrade verification and a real
test of the local countdown and zero-boundary feedback lock.
