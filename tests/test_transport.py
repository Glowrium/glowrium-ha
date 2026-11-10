"""Exercise the real connection logic against a fake GATT peripheral."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import cbor2
import pytest
from bleak import BleakError

from custom_components.glowrium.bluetooth import transport as module
from custom_components.glowrium.bluetooth.advertisement import STATE_UUID, WRITE_UUID

C017_STATE = {1: 0, 7: 2, 8: 1, 9: 0, 10: 80, 15: 50, 23: 0, 24: 10}


@pytest.fixture
def peripheral(hass, advertisement, monkeypatch):
    updates = MagicMock()
    radio = module.BleTransport(hass, advertisement, updates)
    client = SimpleNamespace(
        is_connected=True,
        services=MagicMock(),
        start_notify=AsyncMock(),
        disconnect=AsyncMock(),
    )
    client.services.get_service.return_value = object()

    async def write(uuid, payload, response):
        if uuid == STATE_UUID:
            radio._notification(None, bytearray(cbor2.dumps(C017_STATE)))

    client.write_gatt_char = AsyncMock(side_effect=write)
    connect = AsyncMock(return_value=client)
    monkeypatch.setattr(module, "establish_connection", connect)
    monkeypatch.setattr(
        module.bluetooth, "async_ble_device_from_address", lambda *a, **kw: object()
    )
    return radio, client, connect, updates


async def test_reads_use_write_requests_and_subscribe_notify(peripheral):
    radio, client, connect, updates = peripheral
    await radio.refresh()
    assert radio.online
    client.start_notify.assert_awaited_once_with(STATE_UUID, radio._notification)
    assert all(
        call.args[0] == STATE_UUID for call in client.write_gatt_char.await_args_list
    )
    assert cbor2.loads(client.write_gatt_char.await_args_list[0].args[1]) == [
        1,
        2,
        7,
        8,
        9,
        10,
        14,
        15,
        23,
        24,
    ]
    assert updates.call_args.args[0]["brightness"] == 80
    await radio.close()
    assert not radio.online
    client.disconnect.assert_awaited_once()


async def test_failed_write_reconnects_and_retries_once(peripheral):
    radio, client, connect, updates = peripheral
    await radio.refresh()
    writes = 0
    state = dict(C017_STATE)

    async def write(uuid, payload, response):
        nonlocal writes
        if uuid == STATE_UUID:
            radio._notification(None, bytearray(cbor2.dumps(state)))
        if uuid == WRITE_UUID:
            writes += 1
            if writes == 1:
                raise BleakError("disconnected")
            state.update(cbor2.loads(payload))
            radio._notification(None, bytearray(cbor2.dumps(state)))

    client.write_gatt_char.side_effect = write
    await radio.command("set_brightness", brightness=60)
    assert writes == 2
    assert connect.await_count == 2
    await radio.close()


async def test_concurrent_commands_do_not_overlap_gatt_writes(peripheral):
    radio, client, connect, updates = peripheral
    await radio.refresh()
    active = 0
    state = dict(C017_STATE)

    async def write(uuid, payload, response):
        nonlocal active
        assert active == 0
        active += 1
        await asyncio.sleep(0)
        if uuid == WRITE_UUID:
            state.update(cbor2.loads(payload))
        radio._notification(None, bytearray(cbor2.dumps(state)))
        active -= 1

    client.write_gatt_char.side_effect = write
    await asyncio.gather(radio.command("turn_on"), radio.command("turn_off"))
    await radio.close()


async def test_failed_state_probe_backs_off_and_marks_offline(peripheral):
    radio, client, connect, updates = peripheral
    radio._read_state = AsyncMock(side_effect=TimeoutError())
    with pytest.raises(module.BleUnavailable):
        await radio.refresh()
    assert not radio.online
    connect.reset_mock()
    with pytest.raises(module.BleUnavailable):
        await radio.refresh()
    connect.assert_not_awaited()
    assert updates.call_args.args[0] == {"bleOnline": False}
    await radio.close()


async def test_malformed_notification_cannot_set_online(peripheral):
    radio, client, connect, updates = peripheral
    radio._notification(None, bytearray(b"invalid CBOR"))
    assert not radio.online
    updates.assert_not_called()


async def test_write_timeout_without_readback_is_uncertain(peripheral):
    radio, client, connect, updates = peripheral
    await radio.refresh()
    client.write_gatt_char.side_effect = BleakError("write timed out")
    with pytest.raises(module.BleUnavailable) as error:
        await radio.command("turn_off")
    assert error.value.uncertain
    assert "GATT write failed" in str(error.value)
    assert "readback failed" in str(error.value)
    await radio.close()


async def test_failed_write_readback_confirms_without_second_write(peripheral):
    radio, client, connect, updates = peripheral
    await radio.refresh()
    state = dict(C017_STATE)
    writes = 0

    async def write(uuid, payload, response):
        nonlocal writes
        if uuid == STATE_UUID:
            radio._notification(None, bytearray(cbor2.dumps(state)))
        elif uuid == WRITE_UUID:
            writes += 1
            state.update(cbor2.loads(payload))
            raise BleakError("acknowledgement lost")

    client.write_gatt_char.side_effect = write
    await radio.command("set_brightness", brightness=60)
    assert writes == 1
    assert state[10] == 60
    await radio.close()


async def test_pool_evicts_idle_session_before_opening_next(hass):
    from custom_components.glowrium.bluetooth.pool import BleConnectionPool

    pool = BleConnectionPool(max_connections=1)
    first = MagicMock(last_used=1, busy=False, evict=AsyncMock())
    second = MagicMock(last_used=2, busy=False, evict=AsyncMock())
    await pool.reserve(first)
    await pool.reserve(second)
    first.evict.assert_awaited_once()
    assert pool._sessions == {second}


async def test_pool_does_not_interrupt_busy_command():
    from custom_components.glowrium.bluetooth.pool import BleConnectionPool

    pool = BleConnectionPool(max_connections=1)
    first = MagicMock(last_used=1, busy=True, evict=AsyncMock())
    second = MagicMock(last_used=2, busy=False, evict=AsyncMock())
    await pool.reserve(first)
    with pytest.raises(ConnectionError, match="busy"):
        await pool.reserve(second)
    first.evict.assert_not_awaited()
    assert pool._sessions == {first}
