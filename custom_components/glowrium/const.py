"""Constants for the Glowrium integration."""

from datetime import timedelta

DOMAIN = "glowrium"
PLATFORMS = ["light", "switch", "number", "sensor", "binary_sensor"]
CONF_BRAND = "brand"
CONF_TOKEN = "token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_LINK_ID = "link_id"
CONF_USER_ID = "user_id"
DEFAULT_API_URL = ""
DEFAULT_BRAND = "Glowrium"
DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)
MODEL_C017 = "Glowrium-C017"
MODEL_C045 = "Glowrium-C045"
