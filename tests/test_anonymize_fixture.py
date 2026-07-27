"""Tests for the GroupAlarm fixture anonymizer."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from scripts.anonymize_fixture import Anonymizer, anonymize_document, main


class AnonymizerTests(unittest.TestCase):
    """Verify deterministic, recursive and structure-preserving behavior."""

    def test_recursively_removes_secrets_and_pseudonymizes_sensitive_values(
        self,
    ) -> None:
        source = {
            "Personal-Access-Token": "pat-secret",
            "alarmID": 123,
            "message": "Person Alice needs help",
            "nested": {
                "pushToken": "push-secret",
                "feedback": [
                    {
                        "alarmID": 123,
                        "userID": 456,
                        "name": "Alice Example",
                        "creatorName": "Alice Example",
                        "email": "alice@example.org",
                        "phone": "+49 123 456789",
                    }
                ],
            },
        }

        result = Anonymizer("test-salt").anonymize(source)

        self.assertNotIn("Personal-Access-Token", result)
        nested = result["nested"]
        self.assertIsInstance(nested, dict)
        self.assertNotIn("pushToken", nested)
        feedback = nested["feedback"][0]
        self.assertEqual(result["alarmID"], feedback["alarmID"])
        self.assertNotEqual(result["alarmID"], 123)
        self.assertNotIn("Alice", json.dumps(result))
        self.assertNotIn("example.org", json.dumps(result))
        self.assertNotIn("456789", json.dumps(result))

    def test_same_salt_is_deterministic_and_another_salt_changes_output(
        self,
    ) -> None:
        source = {"id": 42, "name": "Station", "latitude": 50.5}

        first, _ = anonymize_document(source, salt="one")
        second, _ = anonymize_document(source, salt="one")
        different, _ = anonymize_document(source, salt="two")

        self.assertEqual(first, second)
        self.assertNotEqual(first, different)

    def test_preserves_container_shapes_and_useful_scalar_types(self) -> None:
        source = {
            "active": True,
            "count": 3,
            "id": 99,
            "startDate": "2026-07-27T10:15:30+00:00",
            "latitude": "50.812345",
            "longitude": 6.123456,
            "coordinates": ["6.123456", 50.812345],
            "items": [None, False, "ordinary state"],
        }

        result = Anonymizer("shape").anonymize(source)

        self.assertIs(result["active"], True)
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["startDate"], source["startDate"])
        self.assertIsInstance(result["id"], int)
        self.assertIsInstance(result["latitude"], str)
        self.assertIsInstance(result["longitude"], float)
        self.assertEqual(len(result["coordinates"]), 2)
        self.assertEqual(result["items"], [None, False, "ordinary state"])
        self.assertNotEqual(result["coordinates"], source["coordinates"])

    def test_scrubs_embedded_email_phone_and_jwt_from_unknown_text(self) -> None:
        source = {
            "summary": (
                "Contact alice@example.org at +49 123 456789; "
                "credential eyJabc.def.ghi"
            )
        }

        result = Anonymizer("embedded").anonymize(source)
        summary = result["summary"]

        self.assertNotIn("alice@example.org", summary)
        self.assertNotIn("456789", summary)
        self.assertNotIn("eyJabc.def.ghi", summary)
        self.assertIn("example.invalid", summary)

    def test_statistics_never_contain_original_values(self) -> None:
        _, stats = anonymize_document(
            {"token": "top-secret", "userID": 7, "name": "Alice"},
            salt="stats",
        )

        self.assertEqual(
            stats,
            {
                "removed_secret": 1,
                "identifier": 1,
                "name": 1,
            },
        )
        self.assertNotIn("Alice", repr(stats))
        self.assertNotIn("top-secret", repr(stats))

    def test_cli_writes_output_and_refuses_source_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            output = root / "fixture.json"
            source.write_text(
                json.dumps({"userID": 55, "email": "a@example.org"}),
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main([str(source), str(output), "--salt", "cli"]),
                    0,
                )
            written = json.loads(output.read_text(encoding="utf-8"))
            self.assertNotEqual(written["userID"], 55)
            self.assertTrue(written["email"].endswith("@example.invalid"))

            with redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(source), str(source)]), 2)


if __name__ == "__main__":
    unittest.main()
