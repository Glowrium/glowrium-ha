"""One serialized GATT connection per explicitly added local device."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from time import monotonic
from typing import Any

import cbor2
from bleak import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback

from .advertisement import (
    SCAN_UUID,
    SERVICE_UUID,
    STATE_UUID,
    WRITE_UUID,
    GlowriumAdvertisement,
    parse_advertisement,
)
from .pool import BleConnectionPool
from .profiles import DeviceProfile

_LOGGER = logging.getLogger(__name__)


class BleUnavailable(Exception):
    """No usable local connection or state response."""

    def __init__(
        self, message: str = "Bluetooth unavailable", *, uncertain: bool = False
    ):
        super().__init__(message)
        self.uncertain = uncertain


def connection_pool(hass: HomeAssistant) -> BleConnectionPool:
    """Use one budget for setup probes and all local entries."""
    from ..const import DOMAIN

    return hass.data.setdefault(DOMAIN, {}).setdefault("ble_pool", BleConnectionPool())


class BleTransport:
    """Use HA's Bluetooth manager, including active Bluetooth proxies."""

    def __init__(
        self,
        hass: HomeAssistant,
        advertisement: GlowriumAdvertisement,
        on_update: Callable[[dict[str, Any]], None],
        pool: BleConnectionPool | None = None,
    ) -> None:
        self.hass = hass
        self.advertisement = advertisement
        self.profile = DeviceProfile(advertisement.product_key)
        self._on_update = on_update
        self._pool = pool or connection_pool(hass)
        self._client: BleakClientWithServiceCache | None = None
        self._lock = asyncio.Lock()
        self._state_received = asyncio.Event()
        self._frame_received = asyncio.Event()
        self._unsubscribe: Callable[[], None] | None = None
        self._closed = False
        self._retry_after = 0.0
        self._failures = 0
        self._task: asyncio.Task | None = None
        self._online = False
        self._last_state_at = 0.0
        self._last_used = 0.0
        self._yield_until = 0.0

    @property
    def last_used(self) -> float:
        return self._last_used

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    def diagnostics(self) -> dict[str, Any]:
        """Operational status without the hardware MAC or proxy address."""
        now = monotonic()
        return {
            "connected": self.online,
            "state_age_seconds": round(now - self._last_state_at, 1)
            if self._last_state_at
            else None,
            "reconnect_in_seconds": round(max(0, self._retry_after - now), 1),
            "yield_in_seconds": round(max(0, self._yield_until - now), 1),
            "failures": self._failures,
        }

    @property
    def online(self) -> bool:
        return self._online and self._client is not None and self._client.is_connected

    @callback
    def start(self) -> None:
        self._unsubscribe = bluetooth.async_register_callback(
            self.hass,
            self._advertised,
            {"service_uuid": SCAN_UUID, "connectable": True},
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
        for info in bluetooth.async_discovered_service_info(
            self.hass, connectable=True
        ):
            self._advertised(info, None)

    @callback
    def _advertised(self, info, change) -> None:
        parsed = parse_advertisement(info)
        if self._closed or parsed is None or parsed.key != self.advertisement.key:
            return
        self.advertisement = parsed
        if (
            not self.online
            and monotonic() >= self._retry_after
            and monotonic() >= self._yield_until
            and (self._task is None or self._task.done())
        ):
            self._task = self.hass.async_create_task(self._background_refresh())

    async def _background_refresh(self) -> None:
        try:
            await self.refresh()
        except BleUnavailable:
            pass

    @callback
    def _disconnected(self, client) -> None:
        if client is self._client:
            self._online = False
            self._pool.release(self)
            self._on_update({"bleOnline": False})

    @callback
    def _notification(self, sender, payload: bytearray) -> None:
        if self._closed:
            return
        try:
            state = self.profile.update(bytes(payload))
        except (ValueError, TypeError, cbor2.CBORDecodeError, OverflowError):
            _LOGGER.debug("Ignoring malformed Glowrium BLE state")
            return
        if self.profile.ready:
            self._online = True
            self._last_state_at = monotonic()
            self._state_received.set()
            self._frame_received.set()
            self._on_update({**state, "bleOnline": True})

    async def _connect(self) -> None:
        if self._client is not None and self._client.is_connected:
            return
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.advertisement.address, connectable=True
        )
        if device is None:
            raise BleUnavailable(
                "Device is not in range of a connectable Bluetooth adapter"
            )
        try:
            await self._pool.reserve(self)
        except ConnectionError as err:
            raise BleUnavailable(str(err)) from err
        try:
            self.profile.raw.clear()
            self._client = await establish_connection(
                BleakClientWithServiceCache,
                device,
                self.advertisement.name,
                disconnected_callback=self._disconnected,
                max_attempts=2,
                ble_device_callback=lambda: bluetooth.async_ble_device_from_address(
                    self.hass, self.advertisement.address, connectable=True
                ),
            )
            if self._client.services.get_service(SERVICE_UUID) is None:
                raise BleUnavailable("Glowrium service missing")
            await self._client.start_notify(STATE_UUID, self._notification)
            self._last_used = monotonic()
        except Exception:
            await self._disconnect()
            raise

    async def _read_state(self) -> None:
        self.profile.raw.clear()
        self._state_received.clear()
        for request in self.profile.state_requests():
            await self._client.write_gatt_char(STATE_UUID, request, response=True)
        async with asyncio.timeout(10):
            await self._state_received.wait()

    async def refresh(self, *, force: bool = False) -> None:
        async with self._lock:
            if self._closed or (
                not force and monotonic() < max(self._retry_after, self._yield_until)
            ):
                raise BleUnavailable("Bluetooth reconnect is backing off")
            if self.online and not force and monotonic() - self._last_state_at < 180:
                return
            try:
                async with asyncio.timeout(35):
                    await self._connect()
                    await self._read_state()
                self._failures = 0
                self._retry_after = 0
                self._last_used = monotonic()
            except (BleakError, TimeoutError, OSError, BleUnavailable) as err:
                await self._failed()
                raise BleUnavailable(str(err)) from err

    async def _confirm(self, attributes: dict[int, Any]) -> bool:
        # A notify may arrive before write_gatt_char returns.
        if self.profile.confirms(attributes):
            return True
        self._frame_received.clear()
        try:
            async with asyncio.timeout(1.5):
                await self._frame_received.wait()
        except TimeoutError:
            pass
        if self.profile.confirms(attributes):
            return True
        await self._read_state()
        return self.profile.confirms(attributes)

    async def command(self, command: str, **values: Any) -> None:
        async with self._lock:
            if self._closed or monotonic() < self._retry_after:
                raise BleUnavailable("Bluetooth is unavailable")
            # All supported writes are absolute. A failed write may have reached
            # the lamp, so read back before retrying or using another route.
            for attempt in range(2):
                try:
                    async with asyncio.timeout(35):
                        if not self.online:
                            await self._connect()
                            await self._read_state()
                        attributes = self.profile.command_attributes(command, **values)
                except (BleakError, TimeoutError, OSError, BleUnavailable) as err:
                    await self._failed()
                    raise BleUnavailable(str(err)) from err
                try:
                    async with asyncio.timeout(35):
                        await self._client.write_gatt_char(
                            WRITE_UUID, cbor2.dumps(attributes), response=True
                        )
                except (BleakError, TimeoutError, OSError, BleUnavailable) as err:
                    _LOGGER.warning(
                        "Glowrium BLE GATT write failed (%s): %s",
                        type(err).__name__,
                        str(err) or "no detail",
                    )
                    await self._disconnect()
                    try:
                        async with asyncio.timeout(35):
                            await self._connect()
                            await self._read_state()
                    except (BleakError, TimeoutError, OSError, BleUnavailable) as read_err:
                        _LOGGER.warning(
                            "Glowrium BLE readback after write failure failed (%s): %s",
                            type(read_err).__name__,
                            str(read_err) or "no detail",
                        )
                        await self._failed()
                        raise BleUnavailable(
                            f"GATT write failed ({type(err).__name__}: "
                            f"{str(err) or 'no detail'}); readback failed "
                            f"({type(read_err).__name__}: {str(read_err) or 'no detail'})",
                            uncertain=True,
                        ) from err
                    if self.profile.confirms(attributes):
                        self._last_used = monotonic()
                        return
                    if attempt:
                        await self._failed()
                        raise BleUnavailable(
                            f"GATT write failed ({type(err).__name__}: "
                            f"{str(err) or 'no detail'}); readback did not confirm it",
                            uncertain=True,
                        ) from err
                    continue
                try:
                    confirmed = await self._confirm(attributes)
                except (BleakError, TimeoutError, OSError, BleUnavailable) as err:
                    _LOGGER.warning(
                        "Glowrium BLE command readback failed (%s): %s",
                        type(err).__name__,
                        str(err) or "no detail",
                    )
                    await self._failed()
                    raise BleUnavailable(
                        f"GATT write completed; readback failed "
                        f"({type(err).__name__}: {str(err) or 'no detail'})",
                        uncertain=True,
                    ) from err
                if confirmed:
                    self._last_used = monotonic()
                    return
                if attempt:
                    _LOGGER.warning(
                        "Glowrium BLE GATT write completed but changed attributes were not observed"
                    )
                    await self._failed()
                    raise BleUnavailable(
                        "Bluetooth command was not confirmed", uncertain=True
                    )

    async def _failed(self) -> None:
        self._online = False
        self._failures += 1
        self._retry_after = monotonic() + min(30 * 2 ** min(self._failures - 1, 3), 240)
        self._on_update({"bleOnline": False})
        await self._disconnect()

    async def _disconnect(self) -> None:
        client, self._client = self._client, None
        self._online = False
        try:
            if client is not None and client.is_connected:
                try:
                    async with asyncio.timeout(5):
                        await client.disconnect()
                except (BleakError, TimeoutError, OSError):
                    _LOGGER.debug("BLE disconnect failed", exc_info=True)
        finally:
            self._pool.release(self)

    async def evict(self) -> None:
        """Yield an idle slot to another lamp without applying failure backoff."""
        async with self._lock:
            self._yield_until = monotonic() + 60
            self._on_update({"bleOnline": False})
            await self._disconnect()

    async def close(self) -> None:
        self._closed = True
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        async with self._lock:
            await self._disconnect()
