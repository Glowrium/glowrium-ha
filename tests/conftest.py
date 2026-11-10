"""Use real HA classes with mocked radio, cloud HTTP and registry boundaries."""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# HA's radio manager depends on Linux/DBus. Keep HA core real on Windows;
# mock only that external hardware boundary, as the tests also do on Linux.
if sys.platform == "win32":
    radio_module = ModuleType("homeassistant.components.bluetooth")
    radio_module.BluetoothScanningMode = SimpleNamespace(ACTIVE="active")
    radio_module.async_ble_device_from_address = MagicMock()
    radio_module.async_discovered_service_info = MagicMock(return_value=[])
    radio_module.async_register_callback = MagicMock(return_value=MagicMock())
    sys.modules["homeassistant.components.bluetooth"] = radio_module
    # ConfigEntry imports the notification frontend, which starts the HTTP stack.
    # None of these tests exercise the frontend or the HTTP server.
    notification_module = ModuleType("homeassistant.components.persistent_notification")
    notification_module.async_create = MagicMock()
    notification_module.async_dismiss = MagicMock()
    sys.modules["homeassistant.components.persistent_notification"] = (
        notification_module
    )
    zone_module = ModuleType("homeassistant.components.zone")
    zone_module.DEFAULT_RADIUS = 100
    sys.modules["homeassistant.components.zone"] = zone_module

from homeassistant.core import HomeAssistant

from custom_components.glowrium import coordinator as coordinator_module
from custom_components.glowrium.bluetooth.advertisement import GlowriumAdvertisement
from custom_components.glowrium.const import MODEL_C017


@pytest.fixture
def advertisement():
    return GlowriumAdvertisement(
        "AA:BB:CC:DD:EE:FF", "aabbccddeeff", MODEL_C017, 17, 0, 2, "Glowrium-H1"
    )


@pytest.fixture
async def hass(tmp_path):
    instance = HomeAssistant(str(tmp_path))
    yield instance
    await instance.async_block_till_done()


@pytest.fixture
def entry():
    return SimpleNamespace(
        entry_id="cloud-account",
        data={},
        async_start_reauth=MagicMock(),
        async_on_unload=MagicMock(),
    )


@pytest.fixture
def api():
    return SimpleNamespace(
        devices=AsyncMock(return_value=[]),
        state=AsyncMock(return_value={}),
        command=AsyncMock(return_value={"online": True, "brightness": 80}),
    )


@pytest.fixture
def hub(hass, monkeypatch):
    monkeypatch.setattr(
        coordinator_module.er,
        "async_get",
        lambda hass: SimpleNamespace(
            entities={},
            async_update_entity=MagicMock(),
        ),
    )
    monkeypatch.setattr(
        coordinator_module.dr,
        "async_get",
        lambda hass: SimpleNamespace(
            async_get_or_create=MagicMock(),
        ),
    )
    result = coordinator_module.GlowriumCoordinator(hass)
    result._store = SimpleNamespace(
        async_delay_save=MagicMock(),
        async_load=AsyncMock(return_value=None),
        async_save=AsyncMock(),
    )
    result.async_set_updated_data = MagicMock(
        side_effect=lambda data: setattr(result, "data", data)
    )
    return result
