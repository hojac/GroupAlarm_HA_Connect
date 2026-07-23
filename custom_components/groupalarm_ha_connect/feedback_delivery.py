from __future__ import annotations

from collections.abc import Awaitable, Callable


class DurationFeedbackError(Exception):
    """The duration endpoint rejected or could not deliver the feedback."""


def active_device_summaries(devices: object) -> list[dict[str, object]]:
    """Keep only non-sensitive fields from active GroupAlarm devices."""
    if not isinstance(devices, list):
        return []
    return [
        {
            "id": device.get("id"),
            "name": device.get("name"),
            "active": True,
            "isMainDevice": device.get("isMainDevice"),
        }
        for device in devices
        if isinstance(device, dict) and device.get("active") is True
    ]


async def send_feedback(
    *,
    response: bool,
    duration: int | None,
    device_id: int | None,
    send_regular: Callable[[bool], Awaitable[object]],
    send_with_duration: Callable[[int, int], Awaitable[object]],
) -> bool:
    """Send feedback and return whether the regular fallback was required."""
    if not response or not duration or not device_id:
        await send_regular(response)
        return False

    try:
        await send_with_duration(device_id, duration)
    except DurationFeedbackError:
        await send_regular(True)
        return True
    return False
