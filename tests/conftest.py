"""Shared Home Assistant test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def hass_config_dir(tmp_path: Path) -> str:
    """Expose this repository's custom components to the test instance."""
    source = Path(__file__).parents[1] / "custom_components"
    (tmp_path / "custom_components").symlink_to(
        source,
        target_is_directory=True,
    )
    return str(tmp_path)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> None:
    """Enable loading custom integrations in every test."""
