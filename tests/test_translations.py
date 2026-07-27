"""Translation and manifest consistency tests."""

from __future__ import annotations

import json
from pathlib import Path

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


def test_version_and_minimum_home_assistant_are_consistent() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text())
    hacs = json.loads((ROOT / "hacs.json").read_text())
    pyproject = (ROOT / "pyproject.toml").read_text()

    assert manifest["version"] == "0.5.0"
    assert hacs["homeassistant"] == "2026.6.0"
    assert 'version = "0.5.0"' in pyproject
    assert 'requires-python = ">=3.14.2"' in pyproject


def test_custom_integration_does_not_ship_core_strings_file() -> None:
    assert not (INTEGRATION / "strings.json").exists()
