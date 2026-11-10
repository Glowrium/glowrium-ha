"""Diagnostics for Glowrium."""

from time import monotonic

from homeassistant.components.diagnostics import async_redact_data

from . import GlowriumConfigEntry
from .const import CONF_REFRESH_TOKEN, CONF_TOKEN


async def async_get_config_entry_diagnostics(hass, entry: GlowriumConfigEntry):
    """Return non-secret catalog and state information."""
    coordinator = entry.runtime_data
    return {
        "config_entry": async_redact_data(
            dict(entry.data), {CONF_TOKEN, CONF_REFRESH_TOKEN, "device"}
        ),
        "devices": async_redact_data(
            coordinator.devices, {"bluetoothMac", "hardwareKey"}
        ),
        "states": coordinator.data,
        "routes": {
            device_id: {
                "bluetooth": transport.diagnostics() if transport else None,
                "cloud_accounts_configured": len(coordinator.accounts),
                "cloud": [
                    {
                        "account_entry": entry_id,
                        "state_age_seconds": round(monotonic() - seen, 1)
                        if seen is not None
                        else None,
                        "state_online": bool(
                            coordinator._cloud_states.get(entry_id, {})
                            .get(device_id, {})
                            .get("online")
                        ),
                    }
                    for entry_id, catalog in coordinator.catalogs.items()
                    if device_id in catalog.values()
                    for seen in (
                        coordinator._cloud_at.get(entry_id, {}).get(device_id),
                    )
                ],
            }
            for device_id in coordinator.devices
            for transport in (coordinator.ble.get(device_id),)
        },
    }
