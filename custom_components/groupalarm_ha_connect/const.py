"""Constants for GroupAlarm HA Connect."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "groupalarm_ha_connect"
BASE_URL: Final = "https://app.groupalarm.com/api/v1"
INTEGRATION_VERSION: Final = "0.5.2"

CONFIG_ENTRY_VERSION: Final = 3
PLATFORMS: Final = (
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
)

CONF_USER_ID: Final = "user_id"
CONF_ORGANIZATION_IDS: Final = "organization_ids"
CONF_ORGANIZATION_NAMES: Final = "organization_names"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_ORGANIZATION_DURATIONS: Final = "organization_durations"
CONF_FEEDBACK_DEVICE_ID: Final = "feedback_device_id"

LEGACY_CONF_PAT: Final = "personal_access_token"
LEGACY_CONF_ORGANIZATION_ID: Final = "organization_id"
LEGACY_CONF_ORGANIZATION_IDS: Final = "organization_ids"

DEFAULT_SCAN_INTERVAL: Final = 60
MIN_SCAN_INTERVAL: Final = 30
MAX_SCAN_INTERVAL: Final = 900

MIN_ARRIVAL_DURATION: Final = 1
MAX_ARRIVAL_DURATION: Final = 180

REQUEST_TIMEOUT_SECONDS: Final = 30.0

ALARM_GATE_LIMIT: Final = 10
MAX_PARALLEL_ORGANIZATIONS: Final = 4
DETAIL_SAFETY_REFRESH: Final = timedelta(minutes=15)
FEEDBACK_RECONCILIATION_DELAYS: Final = (0.0, 1.0, 2.0)
