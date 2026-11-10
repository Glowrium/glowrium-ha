"""Wire-level regression cases against the existing model definitions."""

from types import SimpleNamespace

import cbor2
import pytest

from custom_components.glowrium.bluetooth.advertisement import (
    SCAN_UUID,
    parse_advertisement,
)
from custom_components.glowrium.bluetooth.profiles import (
    PRESETS,
    DeviceProfile,
    UnsupportedCommand,
)
from custom_components.glowrium.const import MODEL_C017, MODEL_C045
from custom_components.glowrium.identity import hardware_key, normalize_mac


@pytest.mark.parametrize("pid,model", [(17, MODEL_C017), (45, MODEL_C045)])
def test_advertised_hardware_mac_is_not_os_address(pid, model):
    info = SimpleNamespace(
        address="OS-PLATFORM-UUID",
        name="Glowrium",
        service_data={
            SCAN_UUID: bytes([0, 0, 0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF, 7, 0, pid, 3])
        },
    )
    result = parse_advertisement(info)
    assert result.mac == "aabbccddeeff"
    assert result.address == "OS-PLATFORM-UUID"
    assert result.product_key == model
    assert result.sub_id == 3


@pytest.mark.parametrize(
    "payload", [b"", bytes(10), bytes(12), bytes([0, 0, 1, 2, 3, 4, 5, 6, 1, 0, 51])]
)
def test_malformed_or_unsupported_advertisements(payload):
    assert (
        parse_advertisement(
            SimpleNamespace(
                address="addr",
                name="Glowrium-C017",
                service_data={SCAN_UUID: payload},
            )
        )
        is None
    )


def test_identity_normalization():
    assert normalize_mac("AA:BB:CC:DD:EE:FF") == "aabbccddeeff"
    assert normalize_mac("000000000000") is None
    assert normalize_mac("platform UUID") is None
    assert hardware_key("aabbccddeeff", MODEL_C017) != hardware_key(
        "aabbccddeeff", MODEL_C045
    )


def test_model_specific_read_requests():
    c017 = DeviceProfile(MODEL_C017)
    assert cbor2.loads(c017.state_requests()[0]) == [1, 2, 7, 8, 9, 10, 14, 15, 23, 24]
    assert DeviceProfile(MODEL_C045).state_requests() == [
        bytes([1, 2, 19, 22, 23, 101]),
        bytes([24]),
    ]


def test_c017_commands_and_partial_state():
    profile = DeviceProfile(MODEL_C017)
    brightness = cbor2.loads(profile.command("set_brightness", brightness=80))
    assert brightness == {8: True, 10: 80}
    assert type(brightness[8]) is bool
    auxiliary_off = cbor2.loads(profile.command("turn_off", target="auxiliary"))
    assert auxiliary_off == {23: False}
    assert type(auxiliary_off[23]) is bool
    all_on = cbor2.loads(profile.command("turn_on", target="all"))
    assert all_on == {8: True, 23: True}
    assert all(type(value) is bool for value in all_on.values())
    all_off = cbor2.loads(profile.command("turn_off", target="all"))
    assert all_off == {8: False, 23: False}
    assert all(type(value) is bool for value in all_off.values())
    assert cbor2.loads(
        profile.command("set_brightness", target="auxiliary", brightness=12)
    ) == {23: 1, 24: 12}
    assert cbor2.loads(profile.command("set_rhythm", power=True)) == {9: 1}
    profile.update(
        cbor2.dumps({1: 0, 7: 2, 8: 1, 9: 0, 10: 80, 15: 100, 23: 0, 24: 12})
    )
    assert profile.ready
    state = profile.update(cbor2.dumps({23: 1}))
    assert state["brightness"] == 80
    assert state["auxiliaryPower"]
    assert state["colorTemperature"] == 6500
    assert state["effect"] is None
    assert (
        cbor2.loads(profile.command("set_color_temperature", colorTemperature=2700))[15]
        == 0
    )


def test_c017_scene_preserves_schedule_data_and_array_type():
    profile = DeviceProfile(MODEL_C017)
    profile.update(cbor2.dumps({1: 1, 7: 14, 75: [50, 20, 36000, 60000, 900]}))
    command = cbor2.loads(
        profile.command("set_color_temperature", colorTemperature=6500)
    )
    assert command == {75: [50, 100, 36000, 60000, 900]}
    assert cbor2.loads(profile.command("set_effect", effect="LightMode.Reading")) == {
        1: 1,
        7: 2,
    }
    profile.raw[7] = 4
    with pytest.raises(UnsupportedCommand):
        profile.command("set_color_temperature", colorTemperature=4000)


@pytest.mark.parametrize("effect", list(PRESETS["c045"]))
def test_c045_effects_have_byte_strings_and_presets_are_immutable(effect):
    profile = DeviceProfile(MODEL_C045)
    expected = PRESETS["c045"][effect]
    result = cbor2.loads(profile.command("set_effect", effect=effect))
    assert result == {19: bytes(expected["mode"]), 24: bytes(expected["data"])}
    assert len(result[24]) == 100


def test_c045_color_temperature_and_color():
    profile = DeviceProfile(MODEL_C045)
    result = cbor2.loads(
        profile.command("set_color_temperature", colorTemperature=7000)
    )
    assert result[19] == bytes([0, 0, 5])
    assert len(result[22]) == 80 and result[23] == bytes([100] * 20)
    result = cbor2.loads(profile.command("set_color", hue=60, saturation=1))
    assert result[22][:4] == bytes([128, 128, 0, 254])
    assert result[19] == bytes([0, 0, 128])
    profile.update(cbor2.dumps({19: result[19], 22: result[22]}))
    assert profile.normalized()["colorHue"] == 60
    assert profile.normalized()["colorMode"] == "hs"


def test_c045_dynamic_edits_preserve_all_other_bytes():
    profile = DeviceProfile(MODEL_C045)
    original = bytes([2, 20, 0x80 | 51, 40] + list(range(96)))
    profile.update(cbor2.dumps({19: bytes([1, 0, 128]), 24: original}))
    result = cbor2.loads(profile.command("set_effect_speed", speed=80))[24]
    assert result[2] == 0x80 | 21
    assert result[:2] == original[:2] and result[3:] == original[3:]
    result = cbor2.loads(profile.command("set_brightness", brightness=65))[24]
    assert result[3] == 65 and result[4:] == original[4:]
    assert profile.raw[24] == original
    profile.raw[19] = bytes([2, 0, 1])
    with pytest.raises(UnsupportedCommand):
        profile.command("set_brightness", brightness=80)


def test_invalid_notify_never_mutates_retained_state():
    profile = DeviceProfile(MODEL_C045)
    profile.raw[1] = 80
    for payload in ({1: "bad"}, {19: b"short"}, {22: bytes(4)}, {"power": 1}):
        with pytest.raises(ValueError):
            profile.update(cbor2.dumps(payload))
        assert profile.raw == {1: 80}
