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

# Keep protocol model keys stable; only change names shown in Home Assistant.
MODEL_DISPLAY_NAMES = {MODEL_C017: "H1", MODEL_C045: "H4"}


def display_model(product_key: str | None) -> str | None:
    """Return the customer-facing model name without changing device identity."""
    return MODEL_DISPLAY_NAMES.get(product_key, product_key)
