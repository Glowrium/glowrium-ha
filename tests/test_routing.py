"""Account ownership, identity continuity, fallback and state reconciliation."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.glowrium import coordinator as coordinator_module
from custom_components.glowrium.api import GlowriumApiError, GlowriumAuthError
from custom_components.glowrium.bluetooth.profiles import UnsupportedCommand
from custom_components.glowrium.bluetooth.transport import BleUnavailable
from custom_components.glowrium.const import MODEL_C017


def catalog():
    return [
        {
            "id": "existing-cloud-id",
            "name": "Desk light",
            "productKey": MODEL_C017,
            "bluetoothMac": "AA:BB:CC:DD:EE:FF",
            "effects": [],
        }
    ]


def local_entry(advertisement):
    return SimpleNamespace(
        entry_id="local-light",
        data={
            "mode": "bluetooth",
            "device": advertisement.as_dict(),
        },
    )


@pytest.fixture
def radio(monkeypatch):
    transport = SimpleNamespace(
        start=MagicMock(),
        refresh=AsyncMock(),
        command=AsyncMock(),
        close=AsyncMock(),
    )
    monkeypatch.setattr(coordinator_module, "BleTransport", lambda *args: transport)
    return transport


async def test_local_first_then_cloud_uses_one_device(
    hub, entry, api, advertisement, radio
):
    await hub.async_add_local(local_entry(advertisement))
    device_id = next(iter(hub.devices))
    await hub.async_add_account(entry, api, catalog())
    assert list(hub.devices) == [device_id]
    assert hub.catalogs[entry.entry_id]["existing-cloud-id"] == device_id
    assert hub.owners[device_id] == "local-light"
    assert hub._identities[advertisement.key] == device_id


async def test_cloud_first_preserves_legacy_entity_id(
    hub, entry, api, advertisement, radio
):
    await hub.async_add_account(entry, api, catalog())
    await hub.async_add_local(local_entry(advertisement))
    assert list(hub.devices) == ["existing-cloud-id"]
    assert hub.owners["existing-cloud-id"] == entry.entry_id
    assert hub.local_entries["local-light"] == "existing-cloud-id"
    # Persisted identities make both orders on the next restart equivalent.
    assert hub._resolve_id(None, advertisement.key) == "existing-cloud-id"


async def test_cloud_and_ble_without_mac_are_not_guessed_by_name(
    hub, entry, api, advertisement, radio
):
    devices = catalog()
    devices[0].pop("bluetoothMac")
    await hub.async_add_account(entry, api, devices)
    await hub.async_add_local(local_entry(advertisement))
    assert len(hub.devices) == 2


async def test_ble_priority_and_cloud_fallback(hub, entry, api, advertisement, radio):
    await hub.async_add_account(entry, api, catalog())
    await hub.async_add_local(local_entry(advertisement))
    await hub.async_command("existing-cloud-id", "set_brightness", brightness=80)
    api.command.assert_not_awaited()
    radio.command.side_effect = BleUnavailable()
    await hub.async_command("existing-cloud-id", "set_brightness", brightness=80)
    api.command.assert_awaited_once_with(
        "existing-cloud-id", "set_brightness", brightness=80
    )


async def test_local_failure_never_calls_unrelated_account(
    hub, entry, api, advertisement, radio
):
    await hub.async_add_account(entry, api, [])
    await hub.async_add_local(local_entry(advertisement))
    radio.command.side_effect = BleUnavailable("Device is not in range")
    with pytest.raises(
        HomeAssistantError,
        match="Bluetooth control failed before write: Device is not in range",
    ):
        await hub.async_command(next(iter(hub.devices)), "turn_on")
    api.command.assert_not_awaited()


async def test_uncertain_ble_write_does_not_duplicate_over_cloud(
    hub, entry, api, advertisement, radio
):
    await hub.async_add_account(entry, api, catalog())
    await hub.async_add_local(local_entry(advertisement))
    radio.command.side_effect = BleUnavailable("timeout", uncertain=True)
    with pytest.raises(HomeAssistantError, match="may have reached"):
        await hub.async_command("existing-cloud-id", "turn_on")
    api.command.assert_not_awaited()


async def test_unsupported_mode_is_not_retried_on_cloud(
    hub, entry, api, advertisement, radio
):
    await hub.async_add_account(entry, api, catalog())
    await hub.async_add_local(local_entry(advertisement))
    radio.command.side_effect = UnsupportedCommand("unsupported mode")
    with pytest.raises(HomeAssistantError, match="unsupported mode"):
        await hub.async_command("existing-cloud-id", "set_brightness", brightness=20)
    api.command.assert_not_awaited()


async def test_expired_account_does_not_disable_local(
    hub, entry, api, advertisement, radio
):
    await hub.async_add_account(entry, api, catalog())
    await hub.async_add_local(local_entry(advertisement))
    hub._ble_update("existing-cloud-id", {"bleOnline": True, "brightness": 80})
    api.devices.side_effect = GlowriumAuthError()
    await hub._refresh_account(entry.entry_id)
    entry.async_start_reauth.assert_called_once()
    assert hub.data["existing-cloud-id"]["online"]
    assert hub.data["existing-cloud-id"]["brightness"] == 80


async def test_slow_cloud_does_not_overwrite_new_ble_state(
    hub, entry, api, advertisement, radio
):
    await hub.async_add_account(entry, api, catalog())
    api.devices.return_value = catalog()
    pending, release = asyncio.Event(), asyncio.Event()

    async def old_state(cloud_id):
        pending.set()
        await release.wait()
        return {"online": True, "brightness": 20}

    api.state.side_effect = old_state
    task = asyncio.create_task(hub._refresh_account(entry.entry_id))
    await pending.wait()
    hub._ble_update("existing-cloud-id", {"bleOnline": True, "brightness": 80})
    release.set()
    await task
    assert hub.data["existing-cloud-id"]["brightness"] == 80


async def test_stale_ble_state_yields_to_fresh_cloud(
    hub, entry, api, advertisement, radio
):
    await hub.async_add_account(entry, api, catalog())
    await hub.async_add_local(local_entry(advertisement))
    hub._ble_update("existing-cloud-id", {"bleOnline": True, "brightness": 80})
    hub._cloud_states[entry.entry_id]["existing-cloud-id"] = {
        "online": True,
        "brightness": 40,
    }
    now = coordinator_module.monotonic()
    hub._cloud_at[entry.entry_id]["existing-cloud-id"] = now
    hub._ble_at["existing-cloud-id"] = now - 241
    hub._publish_device("existing-cloud-id")
    assert hub.data["existing-cloud-id"]["brightness"] == 40
    assert hub.data["existing-cloud-id"]["stateSource"] == "cloud"


async def test_owner_removal_transfers_entities_to_local(
    hub, entry, api, advertisement, radio, monkeypatch
):
    update = MagicMock()
    registry_entity = SimpleNamespace(
        platform="glowrium",
        unique_id="existing-cloud-id_main_light",
        config_entry_id=entry.entry_id,
        entity_id="light.my_desk",
    )
    monkeypatch.setattr(
        coordinator_module.er,
        "async_get",
        lambda hass: SimpleNamespace(
            entities={"light.my_desk": registry_entity},
            async_update_entity=update,
        ),
    )
    await hub.async_add_account(entry, api, catalog())
    await hub.async_add_local(local_entry(advertisement))
    await hub.async_remove_entry(entry.entry_id)
    update.assert_called_with("light.my_desk", config_entry_id="local-light")
    assert hub.owners["existing-cloud-id"] == "local-light"
    radio.close.assert_not_awaited()
    await hub.async_command("existing-cloud-id", "turn_on")
    radio.command.assert_awaited_once_with("turn_on")


async def test_removing_local_keeps_cloud_route(hub, entry, api, advertisement, radio):
    await hub.async_add_account(entry, api, catalog())
    await hub.async_add_local(local_entry(advertisement))
    await hub.async_remove_entry("local-light")
    radio.close.assert_awaited_once()
    await hub.async_command("existing-cloud-id", "turn_on")
    api.command.assert_awaited_once_with("existing-cloud-id", "turn_on")


async def test_one_device_failure_does_not_discard_healthy_sibling(hub, entry, api):
    devices = catalog() + [{"id": "second", "productKey": MODEL_C017}]
    api.devices.return_value = devices

    async def state(cloud_id):
        if cloud_id == "second":
            raise GlowriumApiError("offline")
        return {"online": True, "brightness": 70}

    api.state.side_effect = state
    await hub.async_add_account(entry, api, devices)
    await hub._refresh_account(entry.entry_id)
    assert hub.data["existing-cloud-id"]["online"]
    assert not hub.data["second"]["online"]


async def test_unbinding_cloud_revokes_cloud_fallback(
    hub, entry, api, advertisement, radio
):
    await hub.async_add_account(entry, api, catalog())
    await hub.async_add_local(local_entry(advertisement))
    hub._sync_catalog(entry.entry_id, [])
    radio.command.side_effect = BleUnavailable()
    with pytest.raises(HomeAssistantError):
        await hub.async_command("existing-cloud-id", "turn_on")
    api.command.assert_not_awaited()


async def test_shared_hub_does_not_inherit_first_config_entry(hub):
    assert hub.config_entry is None


async def test_account_removal_waits_for_inflight_command(hub, entry, api):
    await hub.async_add_account(entry, api, catalog())
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow_command(*args, **kwargs):
        entered.set()
        await release.wait()
        return {"online": True}

    api.command.side_effect = slow_command
    command = asyncio.create_task(hub.async_command("existing-cloud-id", "turn_on"))
    await entered.wait()
    removal = asyncio.create_task(hub.async_remove_entry(entry.entry_id))
    await asyncio.sleep(0)
    assert not removal.done()
    release.set()
    await asyncio.gather(command, removal)
    assert entry.entry_id not in hub.accounts
