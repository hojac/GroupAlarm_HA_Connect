from __future__ import annotations

from typing import Any


def confirmed_feedback_state(item: dict[str, Any]) -> str | None:
    """Map an explicitly confirmed GroupAlarm feedback item to a HA state."""
    state = item.get("state")
    if not isinstance(state, str) or state.strip().upper() != "RESPONDED":
        return None

    response = item.get("feedback")
    if response is True:
        return "komme"
    if response is False:
        return "komme_nicht"
    return None
