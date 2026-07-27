"""Tests for the tracked-file repository safety gate."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_repository import (
    check_files,
    fixture_errors,
    secret_markers,
    tracked_files,
    unsafe_tracked_path,
)


def test_unsafe_tracked_path_rejects_generated_and_secret_files() -> None:
    """Generated Python, tool caches, and local secrets are never published."""
    assert unsafe_tracked_path(Path("tests/__pycache__/test_api.pyc"))
    assert unsafe_tracked_path(Path(".coverage"))
    assert unsafe_tracked_path(Path(".coverage.worker"))
    assert unsafe_tracked_path(Path("coverage.json"))
    assert unsafe_tracked_path(Path("coverage.xml"))
    assert unsafe_tracked_path(Path(".env"))
    assert unsafe_tracked_path(Path("config/secrets.yaml"))
    assert unsafe_tracked_path(Path("custom_components/example/sensor.py")) is None


def test_secret_markers_detect_only_high_confidence_credentials() -> None:
    """Real credential shapes fail while placeholders and API field names pass."""
    github_token = "github_" + "pat_" + "1234567890abcdefghijklmnopqrstuv"
    private_key = "-----BEGIN " + "PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"
    assert secret_markers(f"key = '{github_token}'") == ("GitHub token",)
    assert secret_markers(private_key) == ("private key",)
    assert secret_markers("Personal-Access-Token: <PAT>") == ()
    assert secret_markers("token = 'pat-test-secret'") == ()


def test_fixture_requires_explicit_anonymization_metadata() -> None:
    """Raw-looking JSON cannot be committed as a GroupAlarm fixture."""
    path = Path("tests/fixtures/open_alarm.json")
    assert fixture_errors(path, json.dumps({"alarmID": 123}))
    assert fixture_errors(path, "not JSON") == ("fixture is not valid JSON",)
    assert fixture_errors(path, json.dumps([])) == ("fixture root must be an object",)
    assert (
        fixture_errors(
            path,
            json.dumps(
                {
                    "_fixture_metadata": {
                        "anonymized": True,
                        "source": "groupalarm",
                    },
                    "alarmID": 1_234_567,
                }
            ),
        )
        == ()
    )


def test_check_files_reports_path_secret_and_fixture_violations(
    tmp_path: Path,
) -> None:
    """One CI run reports every independent actionable violation."""
    (tmp_path / "tests/fixtures").mkdir(parents=True)
    (tmp_path / "tests/__pycache__").mkdir()
    (tmp_path / "tests/__pycache__/payload.pyc").write_bytes(b"compiled")
    (tmp_path / "tests/fixtures/raw.json").write_text(
        json.dumps(
            {"token": ("github_" + "pat_" + "1234567890abcdefghijklmnopqrstuv")}
        ),
        encoding="utf-8",
    )

    errors = check_files(
        tmp_path,
        (
            Path("tests/__pycache__/payload.pyc"),
            Path("tests/fixtures/raw.json"),
        ),
    )

    assert errors == [
        "tests/__pycache__/payload.pyc: cache or generated directory",
        "tests/fixtures/raw.json: possible GitHub token",
        (
            "tests/fixtures/raw.json: fixture must declare "
            "_fixture_metadata.anonymized=true and source=groupalarm"
        ),
    ]


def test_current_tracked_repository_passes_safety_gate() -> None:
    """The exact file set intended for publication is clean."""
    root = Path(__file__).parents[1]
    assert check_files(root, tracked_files(root)) == []
