"""Shared device state and routing across independent cloud and BLE entries."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import AsyncExitStack
from time import monotonic
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import GlowriumApi, GlowriumApiError, GlowriumAuthError
from .bluetooth.advertisement import GlowriumAdvertisement
from .bluetooth.profiles import DeviceProfile, UnsupportedCommand
from .bluetooth.transport import BleTransport, BleUnavailable
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, MODEL_C017, MODEL_C045
from .identity import hardware_key

_LOGGER = logging.getLogger(__name__)
SIGNAL_DEVICES = f"{DOMAIN}_devices"


class GlowriumCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """One physical device and entity set, with optional account and BLE routes."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=None,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.devices: dict[str, dict] = {}
        self.data = {}
        self.accounts: dict[str, tuple[ConfigEntry, GlowriumApi]] = {}
        self.catalogs: dict[str, dict[str, str]] = {}
        self.members: dict[str, set[str]] = {}
        self.owners: dict[str, str] = {}
        self.local_entries: dict[str, str] = {}
        self.ble: dict[str, BleTransport] = {}
        self._cloud_states: dict[str, dict[str, dict]] = {}
        self._cloud_at: dict[str, dict[str, float]] = {}
        self._ble_states: dict[str, dict] = {}
        self._ble_at: dict[str, float] = {}
        self._command_at: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._identities: dict[str, str] = {}
        self._store = Store(hass, 1, f"{DOMAIN}.identities")
        self._source_lock = asyncio.Lock()

    async def async_load(self) -> None:
        self._identities = await self._store.async_load() or {}

    def _resolve_id(self, cloud_id: str | None, key: str | None) -> str:
        """Preserve existing cloud IDs and persist the identities of local-first devices."""
        alias = f"cloud:{cloud_id}" if cloud_id else None
        stable = self._identities.get(key) if key else None
        stable = stable or (self._identities.get(alias) if alias else None)
        if stable is None:
            stable = cloud_id or f"ble_{key.lower().replace(':', '_')}"
        if key:
            self._identities[key] = stable
        if alias:
            self._identities[alias] = stable
        self._store.async_delay_save(lambda: self._identities, 1)
        return stable

    @callback
    def device_ids_for_entry(self, entry_id: str) -> list[str]:
        return [key for key, owner in self.owners.items() if owner == entry_id]

    def _register(self, entry_id: str, device_id: str, metadata: dict) -> None:
        self.devices.setdefault(device_id, {}).update(metadata)
        self.members.setdefault(device_id, set()).add(entry_id)
        self.data.setdefault(device_id, {"online": False})
        self._locks.setdefault(device_id, asyncio.Lock())
        dr.async_get(self.hass).async_get_or_create(
            config_entry_id=entry_id,
            identifiers={(DOMAIN, device_id)},
            name=self.devices[device_id].get("name"),
            manufacturer="Glowrium",
            model=self.devices[device_id].get("productKey"),
        )
        if device_id not in self.owners:
            self._set_owner(device_id, entry_id)

    def _set_owner(self, device_id: str, entry_id: str) -> None:
        self.owners[device_id] = entry_id
        # Reuse registry records if an account disappears but a local entry survives.
        registry = er.async_get(self.hass)
        for entity in list(registry.entities.values()):
            if entity.platform == DOMAIN and entity.unique_id.startswith(
                f"{device_id}_"
            ):
                if entity.config_entry_id != entry_id:
                    registry.async_update_entity(
                        entity.entity_id, config_entry_id=entry_id
                    )

    async def async_add_account(
        self, entry: ConfigEntry, api: GlowriumApi, devices: list[dict]
    ) -> None:
        async with self._source_lock:
            self._add_account(entry, api, devices)

    def _add_account(
        self, entry: ConfigEntry, api: GlowriumApi, devices: list[dict]
    ) -> None:
        self.accounts[entry.entry_id] = (entry, api)
        self.catalogs[entry.entry_id] = {}
        self._cloud_states[entry.entry_id] = {}
        self._cloud_at[entry.entry_id] = {}
        self._sync_catalog(entry.entry_id, devices)

    def _sync_catalog(self, entry_id: str, devices: list[dict]) -> None:
        previous = self.catalogs[entry_id]
        current: dict[str, str] = {}
        for device in devices:
            if device.get("productKey") not in (MODEL_C017, MODEL_C045):
                continue
            cloud_id = str(device["id"])
            key = hardware_key(device.get("bluetoothMac"), device["productKey"])
            device_id = self._resolve_id(cloud_id, key)
            current[cloud_id] = device_id
            self._register(
                entry_id, device_id, {**device, "id": device_id, "hardwareKey": key}
            )
        self.catalogs[entry_id] = current
        for device_id in set(previous.values()) - set(current.values()):
            self.members[device_id].discard(entry_id)
            self._cloud_states[entry_id].pop(device_id, None)
            self._cloud_at[entry_id].pop(device_id, None)
            self._publish_device(device_id)
        async_dispatcher_send(self.hass, SIGNAL_DEVICES)

    async def async_add_local(self, entry: ConfigEntry) -> None:
        async with self._source_lock:
            self._add_local(entry)

    def _add_local(self, entry: ConfigEntry) -> None:
        adv = GlowriumAdvertisement(**entry.data["device"])
        device_id = self._resolve_id(None, adv.key)
        existing = self.devices.get(device_id, {})
        self.local_entries[entry.entry_id] = device_id
        self._register(
            entry.entry_id,
            device_id,
            {
                "id": device_id,
                "name": existing.get("name") or adv.name,
                "productKey": adv.product_key,
                "firmwareVersion": existing.get("firmwareVersion") or str(adv.firmware),
                "bluetoothMac": adv.mac,
                "hardwareKey": adv.key,
                "effects": DeviceProfile(adv.product_key).effects,
            },
        )
        transport = BleTransport(
            self.hass, adv, lambda state: self._ble_update(device_id, state)
        )
        self.ble[device_id] = transport
        transport.start()
        async_dispatcher_send(self.hass, SIGNAL_DEVICES)

    @callback
    def _ble_update(self, device_id: str, state: dict) -> None:
        self._ble_states.setdefault(device_id, {}).update(state)
        if state.get("bleOnline"):
            self._ble_at[device_id] = monotonic()
        self._publish_device(device_id)
        self.async_set_updated_data(dict(self.data))

    def _publish_device(self, device_id: str) -> None:
        if device_id not in self.data:
            return
        now = monotonic()
        local = self._ble_states.get(device_id, {})
        cloud = {}
        for entry_id, states in self._cloud_states.items():
            candidate = states.get(device_id, {})
            if (
                candidate.get("online")
                and now - self._cloud_at.get(entry_id, {}).get(device_id, 0) < 90
            ):
                cloud = candidate
                break
        ble_online = (
            bool(local.get("bleOnline")) and now - self._ble_at.get(device_id, 0) < 240
        )
        use_local = ble_online or now - self._ble_at.get(device_id, 0) < 5
        self.data[device_id] = {
            **self.data[device_id],
            **(local if use_local else cloud),
            "online": bool(ble_online or cloud),
            "bleOnline": ble_online,
            "cloudOnline": bool(cloud),
            "controlSource": "bluetooth" if ble_online else "cloud" if cloud else None,
            "stateSource": "bluetooth" if use_local else "cloud" if cloud else None,
        }

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        async with self._source_lock:
            await asyncio.gather(
                *(self._refresh_account(key) for key in list(self.accounts)),
                *(
                    self._refresh_ble(key, value)
                    for key, value in list(self.ble.items())
                ),
            )
            return dict(self.data)

    async def _refresh_ble(self, device_id: str, transport: BleTransport) -> None:
        try:
            await transport.refresh()
        except BleUnavailable:
            pass

    async def _refresh_account(self, entry_id: str) -> None:
        entry, api = self.accounts[entry_id]
        try:
            self._sync_catalog(entry_id, await api.devices())
        except GlowriumAuthError:
            entry.async_start_reauth(self.hass)
            self._cloud_states[entry_id] = {}
            self._cloud_at[entry_id] = {}
        except GlowriumApiError:
            self._cloud_states[entry_id] = {}
            self._cloud_at[entry_id] = {}
            _LOGGER.debug("Cloud catalog unavailable", exc_info=True)
        else:

            async def refresh_one(cloud_id: str, device_id: str) -> None:
                started = monotonic()
                try:
                    state = await api.state(cloud_id)
                except GlowriumAuthError:
                    entry.async_start_reauth(self.hass)
                    self._cloud_states[entry_id].pop(device_id, None)
                    self._cloud_at[entry_id].pop(device_id, None)
                except GlowriumApiError:
                    self._cloud_states[entry_id].pop(device_id, None)
                    self._cloud_at[entry_id].pop(device_id, None)
                else:
                    if not self._locks[
                        device_id
                    ].locked() and started >= self._command_at.get(device_id, 0):
                        self._cloud_states[entry_id][device_id] = state
                        self._cloud_at[entry_id][device_id] = monotonic()

            await asyncio.gather(
                *(
                    refresh_one(cloud_id, device_id)
                    for cloud_id, device_id in self.catalogs[entry_id].items()
                )
            )
        for device_id in self.catalogs.get(entry_id, {}).values():
            self._publish_device(device_id)

    async def async_command(self, device_id: str, command: str, **values: Any) -> None:
        async with self._locks[device_id]:
            self._command_at[device_id] = monotonic()
            transport = self.ble.get(device_id)
            ble_error: BleUnavailable | None = None
            if transport:
                try:
                    await transport.command(command, **values)
                except UnsupportedCommand as err:
                    raise HomeAssistantError(str(err)) from err
                except BleUnavailable as err:
                    if err.uncertain:
                        raise HomeAssistantError(
                            "Bluetooth write may have reached the light; "
                            f"verify its state before retrying. Reason: {err}"
                        ) from err
                    ble_error = err
                    _LOGGER.warning("BLE command failed before write: %s", err)
                else:
                    await self._refresh_ble(device_id, transport)
                    self.async_set_updated_data(dict(self.data))
                    return
            last_error = None
            cloud_matched = False
            for entry_id, (entry, api) in list(self.accounts.items()):
                cloud_id = next(
                    (
                        key
                        for key, value in self.catalogs[entry_id].items()
                        if value == device_id
                    ),
                    None,
                )
                if cloud_id is None:
                    continue
                cloud_matched = True
                try:
                    state = await api.command(cloud_id, command, **values)
                except GlowriumAuthError as err:
                    entry.async_start_reauth(self.hass)
                    last_error = err
                except GlowriumApiError as err:
                    last_error = err
                else:
                    if command in ("set_color", "set_color_temperature"):
                        state["colorMode"] = (
                            "hs" if command == "set_color" else "color_temp"
                        )
                    self._cloud_states[entry_id][device_id] = state
                    self._cloud_at[entry_id][device_id] = monotonic()
                    self._ble_at[device_id] = 0
                    self._publish_device(device_id)
                    self.async_set_updated_data(dict(self.data))
                    return
            if ble_error is not None:
                reason = str(ble_error).strip() or "connection or state read timed out"
                if not cloud_matched:
                    raise HomeAssistantError(
                        f"Bluetooth control failed before write: {reason}. "
                        "No linked cloud account can control this light."
                    ) from ble_error
                raise HomeAssistantError(
                    f"Bluetooth control failed before write: {reason}. "
                    "The linked cloud command also failed."
                ) from last_error
            if cloud_matched:
                raise HomeAssistantError("Linked cloud command failed") from last_error
            raise HomeAssistantError(
                "No Bluetooth or linked cloud control route is configured for this light"
            )

    async def async_remove_entry(self, entry_id: str) -> None:
        async with self._source_lock:
            async with AsyncExitStack() as stack:
                for device_id, members in sorted(self.members.items()):
                    if entry_id in members or self.owners.get(device_id) == entry_id:
                        await stack.enter_async_context(self._locks[device_id])
                await self._remove_entry(entry_id)

    async def _remove_entry(self, entry_id: str) -> None:
        self.accounts.pop(entry_id, None)
        self.catalogs.pop(entry_id, None)
        self._cloud_states.pop(entry_id, None)
        self._cloud_at.pop(entry_id, None)
        local_id = self.local_entries.pop(entry_id, None)
        if local_id is not None:
            transport = self.ble.pop(local_id, None)
            if transport:
                await transport.close()
            self._ble_states.pop(local_id, None)
            self._ble_at.pop(local_id, None)
        for device_id, members in list(self.members.items()):
            members.discard(entry_id)
            if self.owners.get(device_id) == entry_id:
                if members:
                    self._set_owner(device_id, sorted(members)[0])
                else:
                    self.owners.pop(device_id, None)
            self._publish_device(device_id)
        self.async_set_updated_data(dict(self.data))
        async_dispatcher_send(self.hass, SIGNAL_DEVICES)

    def async_register_entities(
        self,
        entry: ConfigEntry,
        async_add_entities: Callable,
        factory: Callable,
    ) -> None:
        """Add newly discovered or transferred devices once per entry/platform."""
        added: set[str] = set()

        @callback
        def add_devices() -> None:
            entities = []
            for device_id in self.device_ids_for_entry(entry.entry_id):
                if device_id not in added:
                    added.add(device_id)
                    entities.extend(factory(self, device_id))
            if entities:
                async_add_entities(entities)

        entry.async_on_unload(
            async_dispatcher_connect(self.hass, SIGNAL_DEVICES, add_devices)
        )
        add_devices()

    async def async_close(self) -> None:
        for transport in list(self.ble.values()):
            await transport.close()
        await self._store.async_save(self._identities)
        await self.async_shutdown()
