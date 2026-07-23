from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "groupalarm_ha_connect"
    / "feedback_delivery.py"
)
SPEC = importlib.util.spec_from_file_location("groupalarm_feedback_delivery", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FeedbackDeliveryTest(unittest.TestCase):
    def test_positive_duration_uses_app_endpoint(self) -> None:
        calls: list[tuple[object, ...]] = []

        async def regular(response: bool) -> None:
            calls.append(("regular", response))

        async def timed(device_id: int, duration: int) -> None:
            calls.append(("timed", device_id, duration))

        fallback = asyncio.run(
            MODULE.send_feedback(
                response=True,
                duration=5,
                device_id=258933,
                send_regular=regular,
                send_with_duration=timed,
            )
        )
        self.assertFalse(fallback)
        self.assertEqual(calls, [("timed", 258933, 5)])

    def test_negative_feedback_never_sends_duration(self) -> None:
        calls: list[tuple[object, ...]] = []

        async def regular(response: bool) -> None:
            calls.append(("regular", response))

        async def timed(device_id: int, duration: int) -> None:
            calls.append(("timed", device_id, duration))

        asyncio.run(
            MODULE.send_feedback(
                response=False,
                duration=5,
                device_id=258933,
                send_regular=regular,
                send_with_duration=timed,
            )
        )
        self.assertEqual(calls, [("regular", False)])

    def test_failed_duration_falls_back_without_time(self) -> None:
        calls: list[tuple[object, ...]] = []

        async def regular(response: bool) -> None:
            calls.append(("regular", response))

        async def timed(device_id: int, duration: int) -> None:
            calls.append(("timed", device_id, duration))
            raise MODULE.DurationFeedbackError("device rejected")

        fallback = asyncio.run(
            MODULE.send_feedback(
                response=True,
                duration=2,
                device_id=325111,
                send_regular=regular,
                send_with_duration=timed,
            )
        )
        self.assertTrue(fallback)
        self.assertEqual(calls, [("timed", 325111, 2), ("regular", True)])

    def test_failed_fallback_propagates(self) -> None:
        async def regular(response: bool) -> None:
            raise RuntimeError("regular failed")

        async def timed(device_id: int, duration: int) -> None:
            raise MODULE.DurationFeedbackError("device rejected")

        with self.assertRaisesRegex(RuntimeError, "regular failed"):
            asyncio.run(
                MODULE.send_feedback(
                    response=True,
                    duration=2,
                    device_id=325111,
                    send_regular=regular,
                    send_with_duration=timed,
                )
            )

    def test_device_summaries_exclude_push_tokens_and_inactive_devices(self) -> None:
        devices = MODULE.active_device_summaries(
            [
                {
                    "id": 258933,
                    "name": "iPhone",
                    "active": True,
                    "isMainDevice": False,
                    "pushToken": "secret",
                },
                {
                    "id": 325111,
                    "name": "Altgerät",
                    "active": False,
                    "pushToken": "also-secret",
                },
            ]
        )
        self.assertEqual(
            devices,
            [
                {
                    "id": 258933,
                    "name": "iPhone",
                    "active": True,
                    "isMainDevice": False,
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
