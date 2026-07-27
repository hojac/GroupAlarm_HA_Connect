#!/usr/bin/env python3
"""Anonymize GroupAlarm JSON payloads before they become test fixtures.

The transformation is deterministic for the same salt. It removes credentials,
pseudonymizes identifiers and personal/location data, and preserves the JSON
container structure and scalar types where practical.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

DEFAULT_SALT = "groupalarm-ha-connect-fixture-v1"

_EMAIL_RE = re.compile(
    r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])",
    re.IGNORECASE,
)
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_PHONE_RE = re.compile(
    r"(?<!\w)(?:\+\d[\d ()/.-]{6,}\d|\d{8,15}|\d[\d ()/]{6,}\d)(?!\w)"
)

_SECRET_KEYS = {
    "apikey",
    "apitoken",
    "authentication",
    "authorization",
    "bearer",
    "clientsecret",
    "cookie",
    "confirmpin",
    "confirmtoken",
    "credential",
    "credentials",
    "jwt",
    "password",
    "personalaccesstoken",
    "pushtoken",
    "refreshtoken",
    "secret",
    "session",
    "token",
}

_ID_KEYS = {
    "alarmid",
    "creatorid",
    "deviceid",
    "eventid",
    "externalid",
    "feedbackid",
    "groupid",
    "id",
    "invitationid",
    "labelid",
    "organizationid",
    "organizationids",
    "ownerid",
    "ownerids",
    "parentid",
    "resourceid",
    "tagid",
    "templateid",
    "unitid",
    "userid",
    "userids",
}

_NAME_KEYS = {
    "contactname",
    "displayname",
    "firstname",
    "fullname",
    "lastname",
    "name",
    "names",
    "surname",
    "username",
}

_EMAIL_KEYS = {"email", "emailaddress", "emails", "mail"}
_PHONE_KEYS = {
    "cellphone",
    "mobile",
    "mobilephone",
    "phone",
    "phonenumber",
    "phonenumbers",
    "phones",
    "telephone",
}
_ADDRESS_KEYS = {
    "address",
    "city",
    "country",
    "housenumber",
    "location",
    "place",
    "postalcode",
    "postcode",
    "street",
    "streetname",
    "town",
    "village",
    "zip",
    "zipcode",
}
_FREE_TEXT_KEYS = {
    "alarmmessage",
    "alarmtext",
    "comment",
    "description",
    "keyword",
    "message",
    "note",
    "notes",
    "optionaltext",
    "remark",
    "remarks",
    "text",
    "title",
    "usercomment",
}
_URL_KEYS = {"avatarurl", "imageurl", "url"}
_LATITUDE_KEYS = {"lat", "latitude"}
_LONGITUDE_KEYS = {"lng", "lon", "longitude"}
_COORDINATE_ARRAY_KEYS = {"coordinate", "coordinates", "position"}


def _normalize_key(key: str) -> str:
    """Normalize a key for case- and separator-insensitive comparisons."""
    return re.sub(r"[^a-z0-9]", "", key.casefold())


def _looks_secret(key: str) -> bool:
    normalized = _normalize_key(key)
    return (
        normalized in _SECRET_KEYS
        or "token" in normalized
        or "password" in normalized
        or "secret" in normalized
    )


def _looks_like_id(key: str) -> bool:
    normalized = _normalize_key(key)
    if normalized in _ID_KEYS:
        return True
    return bool(
        re.search(r"(?:^|[_-])ids?$", key, re.IGNORECASE)
        or re.search(r"(?:ID|Id|IDs|Ids)$", key)
    )


class Anonymizer:
    """Deterministically anonymize one or more related JSON documents."""

    def __init__(self, salt: str = DEFAULT_SALT) -> None:
        if not salt:
            raise ValueError("salt must not be empty")
        self._key = hashlib.sha256(salt.encode("utf-8")).digest()
        self.stats: Counter[str] = Counter()

    def anonymize(self, value: JsonValue) -> JsonValue:
        """Return an anonymized copy of a JSON-compatible value."""
        return self._walk(value, key=None)

    def _digest(self, category: str, value: object, length: int = 12) -> str:
        payload = f"{category}:{type(value).__name__}:{value}".encode()
        return hashlib.blake2b(
            payload,
            key=self._key,
            digest_size=16,
        ).hexdigest()[:length]

    def _pseudo_id(self, value: JsonScalar) -> JsonScalar:
        if value is None or isinstance(value, bool):
            return value
        digest = self._digest("id", value, length=16)
        number = 1_000_000 + (int(digest, 16) % 8_000_000)
        if isinstance(value, int):
            return number
        if isinstance(value, float):
            return float(number)
        if isinstance(value, str) and value.isdecimal():
            return str(number)
        return f"id-{digest[:12]}"

    def _pseudo_text(self, category: str, value: str) -> str:
        return f"{category}-{self._digest(category, value)}"

    def _pseudo_coordinate(self, value: int | float, axis: str) -> float:
        digest = int(self._digest(axis, value, length=16), 16)
        fraction = digest / float(0xFFFFFFFFFFFFFFFF)
        if axis == "latitude":
            return round(-60.0 + fraction * 120.0, 6)
        if axis == "longitude":
            return round(-150.0 + fraction * 300.0, 6)
        return round(-1.0 + fraction * 2.0, 6)

    def _pseudo_coordinate_value(
        self,
        value: JsonScalar,
        axis: str,
    ) -> JsonScalar:
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, int | float):
            return self._pseudo_coordinate(value, axis)
        if isinstance(value, str):
            try:
                parsed = float(value)
            except ValueError:
                return self._pseudo_text("coordinate", value)
            return str(self._pseudo_coordinate(parsed, axis))
        return value

    def _scrub_embedded(self, value: str) -> str:
        def email_replacement(match: re.Match[str]) -> str:
            self.stats["embedded_email"] += 1
            return f"anon-{self._digest('email', match.group(0))}@example.invalid"

        def phone_replacement(match: re.Match[str]) -> str:
            self.stats["embedded_phone"] += 1
            return self._pseudo_text("phone", match.group(0))

        value = _JWT_RE.sub("<removed-jwt>", value)
        value = _EMAIL_RE.sub(email_replacement, value)
        return _PHONE_RE.sub(phone_replacement, value)

    def _walk(self, value: JsonValue, key: str | None) -> JsonValue:
        if isinstance(value, dict):
            output: dict[str, JsonValue] = {}
            for child_key, child_value in value.items():
                if _looks_secret(child_key):
                    self.stats["removed_secret"] += 1
                    continue
                output[child_key] = self._walk(child_value, child_key)
            return output

        if isinstance(value, list):
            normalized = _normalize_key(key or "")
            if normalized in _COORDINATE_ARRAY_KEYS:
                output: list[JsonValue] = []
                for index, item in enumerate(value):
                    if (
                        isinstance(item, int | float) and not isinstance(item, bool)
                    ) or (isinstance(item, str) and self._is_numeric_string(item)):
                        output.append(
                            self._pseudo_coordinate_value(
                                item,
                                f"coordinate-{index}",
                            )
                        )
                        self.stats["coordinate"] += 1
                    else:
                        output.append(self._walk(item, key))
                return output
            return [self._walk(item, key) for item in value]

        if key is None:
            return self._scrub_embedded(value) if isinstance(value, str) else value

        normalized = _normalize_key(key)

        if _looks_like_id(key):
            self.stats["identifier"] += 1
            return self._pseudo_id(value)

        if normalized in _LATITUDE_KEYS:
            self.stats["coordinate"] += 1
            return self._pseudo_coordinate_value(value, "latitude")

        if normalized in _LONGITUDE_KEYS:
            self.stats["coordinate"] += 1
            return self._pseudo_coordinate_value(value, "longitude")

        if not isinstance(value, str):
            return value

        if normalized in _EMAIL_KEYS:
            self.stats["email"] += 1
            return f"anon-{self._digest('email', value)}@example.invalid"
        if normalized in _PHONE_KEYS:
            self.stats["phone"] += 1
            return self._pseudo_text("phone", value)
        if normalized in _NAME_KEYS or normalized.endswith(("name", "names")):
            self.stats["name"] += 1
            return self._pseudo_text("name", value)
        if normalized in _ADDRESS_KEYS:
            self.stats["location"] += 1
            return self._pseudo_text("location", value)
        if normalized in _FREE_TEXT_KEYS:
            self.stats["free_text"] += 1
            return self._pseudo_text("redacted-text", value)
        if normalized in _URL_KEYS or normalized.endswith("url"):
            self.stats["url"] += 1
            return self._pseudo_text("redacted-url", value)

        return self._scrub_embedded(value)

    @staticmethod
    def _is_numeric_string(value: str) -> bool:
        try:
            float(value)
        except ValueError:
            return False
        return True


def anonymize_document(
    value: JsonValue,
    *,
    salt: str = DEFAULT_SALT,
) -> tuple[JsonValue, Counter[str]]:
    """Anonymize a document and return it together with aggregate statistics."""
    anonymizer = Anonymizer(salt)
    result = anonymizer.anonymize(value)
    return result, anonymizer.stats


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deterministically anonymize a GroupAlarm JSON fixture.",
    )
    parser.add_argument("input", type=Path, help="source JSON payload")
    parser.add_argument("output", type=Path, help="anonymized JSON fixture")
    parser.add_argument(
        "--salt",
        default=os.environ.get("GROUPALARM_FIXTURE_SALT", DEFAULT_SALT),
        help=(
            "pseudonymization salt; defaults to GROUPALARM_FIXTURE_SALT or "
            "a project constant"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow input and output to refer to the same file",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the command-line anonymizer."""
    args = _parse_args(argv)
    source = args.input.resolve()
    target = args.output.resolve()

    if source == target and not args.force:
        print(
            "Refusing to overwrite the source; choose another output or use --force.",
            file=sys.stderr,
        )
        return 2

    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as err:
        print(f"Could not read valid JSON from {source.name}: {err}", file=sys.stderr)
        return 2

    anonymized, stats = anonymize_document(document, salt=args.salt)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(anonymized, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    summary = ", ".join(f"{key}={stats[key]}" for key in sorted(stats))
    print(f"Wrote {target.name}; {summary or 'no sensitive fields detected'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
