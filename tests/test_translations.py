"""Translation and manifest consistency tests."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.groupalarm_ha_connect.const import INTEGRATION_VERSION

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "groupalarm_ha_connect"


def _translation_shape(value: object) -> object:
    if isinstance(value, dict):
        return {key: _translation_shape(item) for key, item in value.items()}
    return str


def test_translation_key_parity() -> None:
    english = json.loads((INTEGRATION / "translations" / "en.json").read_text())
    german = json.loads((INTEGRATION / "translations" / "de.json").read_text())

    assert _translation_shape(english) == _translation_shape(german)
    assert set(english["entity"]["sensor"]["my_feedback"]["state"]) == {
        "no_alarm",
        "unknown",
        "komme",
        "komme_nicht",
    }
    assert set(english["entity"]) == {
        "binary_sensor",
        "button",
        "device_tracker",
        "sensor",
    }
    assert set(english["exceptions"]) == {
        "feedback_authentication",
        "feedback_busy",
        "feedback_configuration",
        "feedback_conflict",
        "feedback_duration_unverified",
        "feedback_failed",
        "feedback_not_confirmed",
        "feedback_outcome_unknown",
        "feedback_pending",
        "feedback_permission",
        "feedback_rate_limited",
        "feedback_rejected",
        "feedback_sent_without_duration",
        "feedback_superseded",
        "feedback_unavailable",
    }
    assert set(english["issues"]) == {"invalid_feedback_device"}


def test_version_and_minimum_home_assistant_are_consistent() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text())
    hacs = json.loads((ROOT / "hacs.json").read_text())
    pyproject = (ROOT / "pyproject.toml").read_text()

    assert manifest["version"] == "0.5.0"
    assert manifest["version"] == INTEGRATION_VERSION
    assert hacs["homeassistant"] == "2026.6.0"
    assert 'version = "0.5.0"' in pyproject
    assert 'requires-python = ">=3.14.2"' in pyproject


def test_custom_integration_does_not_ship_core_strings_file() -> None:
    assert not (INTEGRATION / "strings.json").exists()
