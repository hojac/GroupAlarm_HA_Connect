#!/usr/bin/env python3
"""Fail CI for tracked build artifacts, credentials, or unsafe fixtures."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

_CACHE_PARTS = {
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    "htmlcov",
}
_FORBIDDEN_NAMES = {
    ".coverage",
    ".env",
    "coverage.json",
    "coverage.xml",
    "secrets.yaml",
}
_FORBIDDEN_SUFFIXES = {
    ".pyc",
    ".pyo",
}
_SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "JWT": re.compile(
        r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\."
        r"[A-Za-z0-9_-]{12,}\b"
    ),
}
_FIXTURE_ROOT = Path("tests/fixtures")
_FIXTURE_METADATA = "_fixture_metadata"


def unsafe_tracked_path(path: Path) -> str | None:
    """Return why a tracked path must never enter the repository."""
    if any(part in _CACHE_PARTS for part in path.parts):
        return "cache or generated directory"
    if path.name in _FORBIDDEN_NAMES or path.name.startswith(".coverage."):
        return "local secret or coverage artifact"
    if path.suffix.casefold() in _FORBIDDEN_SUFFIXES:
        return "compiled Python artifact"
    return None


def secret_markers(text: str) -> tuple[str, ...]:
    """Return high-confidence credential types found in text."""
    return tuple(
        name for name, pattern in _SECRET_PATTERNS.items() if pattern.search(text)
    )


def fixture_errors(path: Path, text: str) -> tuple[str, ...]:
    """Require explicit anonymization metadata on committed JSON fixtures."""
    if path.suffix.casefold() != ".json":
        return ()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ("fixture is not valid JSON",)
    if not isinstance(payload, dict):
        return ("fixture root must be an object",)
    metadata = payload.get(_FIXTURE_METADATA)
    if (
        not isinstance(metadata, dict)
        or metadata.get("anonymized") is not True
        or metadata.get("source") != "groupalarm"
    ):
        return (
            "fixture must declare _fixture_metadata.anonymized=true "
            "and source=groupalarm",
        )
    return ()


def check_files(root: Path, tracked_files: Iterable[Path]) -> list[str]:
    """Return deterministic repository-safety violations."""
    errors: list[str] = []
    for relative in sorted(tracked_files):
        path_error = unsafe_tracked_path(relative)
        if path_error is not None:
            errors.append(f"{relative}: {path_error}")
            continue

        absolute = root / relative
        try:
            content = absolute.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        errors.extend(
            f"{relative}: possible {marker}" for marker in secret_markers(content)
        )

        if relative.is_relative_to(_FIXTURE_ROOT):
            errors.extend(
                f"{relative}: {message}"
                for message in fixture_errors(relative, content)
            )
    return errors


def tracked_files(root: Path) -> tuple[Path, ...]:
    """Read the exact file set Git would publish."""
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        check=True,
        capture_output=True,
    )
    return tuple(
        path
        for value in result.stdout.split(b"\0")
        if value
        for path in (Path(value.decode()),)
        if (root / path).is_file()
    )


def main() -> int:
    """Check the current repository and print only actionable findings."""
    root = Path(__file__).resolve().parents[1]
    errors = check_files(root, tracked_files(root))
    if not errors:
        print("Repository safety checks passed.")
        return 0
    print("\n".join(errors), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
