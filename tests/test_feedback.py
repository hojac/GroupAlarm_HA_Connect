from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "groupalarm_ha_connect"
    / "feedback.py"
)
SPEC = importlib.util.spec_from_file_location("groupalarm_feedback", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ConfirmedFeedbackStateTest(unittest.TestCase):
    def test_responded_positive_is_coming(self) -> None:
        self.assertEqual(
            MODULE.confirmed_feedback_state(
                {"state": "RESPONDED", "feedback": True}
            ),
            "komme",
        )

    def test_responded_negative_is_not_coming(self) -> None:
        self.assertEqual(
            MODULE.confirmed_feedback_state(
                {"state": "RESPONDED", "feedback": False}
            ),
            "komme_nicht",
        )

    def test_false_without_response_confirmation_is_unknown(self) -> None:
        for state in ("UNAVAILABLE", "TIMEDOUT", None):
            with self.subTest(state=state):
                self.assertIsNone(
                    MODULE.confirmed_feedback_state(
                        {"state": state, "feedback": False}
                    )
                )

    def test_response_state_is_case_insensitive(self) -> None:
        self.assertEqual(
            MODULE.confirmed_feedback_state(
                {"state": " responded ", "feedback": True}
            ),
            "komme",
        )

    def test_non_boolean_feedback_is_not_confirmed(self) -> None:
        self.assertIsNone(
            MODULE.confirmed_feedback_state(
                {"state": "RESPONDED", "feedback": "false"}
            )
        )


if __name__ == "__main__":
    unittest.main()
