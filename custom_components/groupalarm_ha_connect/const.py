from __future__ import annotations

DOMAIN = "groupalarm_ha_connect"
BASE_URL = "https://app.groupalarm.com/api/v1"

CONF_PAT = "personal_access_token"
CONF_ORG_ID = "organization_id"  # legacy single-organization key
CONF_ORG_IDS = "organization_ids"
CONF_ORG_NAMES = "organization_names"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 60
PLATFORMS = ["sensor", "binary_sensor", "button", "device_tracker"]
