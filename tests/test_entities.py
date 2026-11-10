"""C017 presents one light with independent power and brightness controls."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_EFFECT

from custom_components.glowrium import light, number, switch
from custom_components.glowrium.const import MODEL_C017, MODEL_C045


@pytest.fixture
def hub():
    result = MagicMock()
    result.devices = {"desk": {"productKey": MODEL_C017, "name": "Desk light"}}
    result.data = {
        "desk": {
            "online": True,
            "power": True,
            "mainPower": False,
            "auxiliaryPower": True,
            "brightness": 40,
            "auxiliaryBrightness": 60,
        }
    }
    result.async_command = AsyncMock()
    return result


async def test_c017_light_is_combined_and_preserves_main_brightness(hub):
    entity = light.GlowriumMainLight(hub, "desk")
    assert entity.is_on
    assert entity.brightness == round(40 * 255 / 100)

    await entity.async_turn_off()
    hub.async_command.assert_awaited_once_with("desk", "turn_off", target="all")
    hub.async_command.reset_mock()

    await entity.async_turn_on()
    hub.async_command.assert_awaited_once_with("desk", "turn_on", target="all")

    hub.async_command.reset_mock()
    await entity.async_turn_on(**{ATTR_BRIGHTNESS: 128})
    hub.async_command.assert_awaited_once_with(
        "desk", "set_brightness", brightness=round(128 * 100 / 255)
    )


async def test_effect_names_hide_prefix_but_commands_keep_protocol_value(hub):
    hub.devices["desk"]["effects"] = ["LightMode.Reading", "LightMode.Mood"]
    hub.data["desk"]["effect"] = "LightMode.Mood"
    entity = light.GlowriumMainLight(hub, "desk")

    assert entity.effect_list == ["Reading", "Mood"]
    assert entity.effect == "Mood"
    await entity.async_turn_on(**{ATTR_EFFECT: "Reading"})
    assert hub.async_command.await_args_list == [
        call("desk", "set_effect", effect="LightMode.Reading"),
        call("desk", "turn_on", target="all"),
    ]


async def test_c017_independent_switches_and_auxiliary_brightness(hub):
    main = switch.GlowriumMainPowerSwitch(hub, "desk")
    auxiliary = switch.GlowriumAuxiliaryPowerSwitch(hub, "desk")
    brightness = number.GlowriumAuxiliaryBrightness(hub, "desk")

    assert not main.is_on
    assert auxiliary.is_on
    assert auxiliary.name == "Mood light"
    assert brightness.native_value == 60
    assert brightness.name == "Mood brightness"

    await main.async_turn_on()
    hub.async_command.assert_awaited_with("desk", "turn_on", target="main")
    await auxiliary.async_turn_off()
    hub.async_command.assert_awaited_with("desk", "turn_off", target="auxiliary")
    await brightness.async_set_native_value(25)
    hub.async_command.assert_awaited_with(
        "desk", "set_brightness", target="auxiliary", brightness=25
    )


async def test_light_setup_removes_old_auxiliary_entity(hub, monkeypatch):
    registry = MagicMock()
    registry.async_get_entity_id.return_value = "light.old_auxiliary"
    monkeypatch.setattr(light.er, "async_get", lambda hass: registry)
    added = []
    hub.async_register_entities.side_effect = (
        lambda entry, async_add_entities, factory: added.extend(factory(hub, "desk"))
    )

    await light.async_setup_entry(object(), SimpleNamespace(runtime_data=hub), None)

    assert len(added) == 1
    assert isinstance(added[0], light.GlowriumMainLight)
    registry.async_remove.assert_called_once_with("light.old_auxiliary")


async def test_switch_setup_removes_old_total_power_entity(hub, monkeypatch):
    registry = MagicMock()
    registry.async_get_entity_id.return_value = "switch.old_total_power"
    monkeypatch.setattr(switch.er, "async_get", lambda hass: registry)
    added = []
    hub.async_register_entities.side_effect = (
        lambda entry, async_add_entities, factory: added.extend(factory(hub, "desk"))
    )

    await switch.async_setup_entry(object(), SimpleNamespace(runtime_data=hub), None)

    assert [type(entity) for entity in added] == [
        switch.GlowriumMainPowerSwitch,
        switch.GlowriumAuxiliaryPowerSwitch,
        switch.GlowriumRhythmSwitch,
    ]
    registry.async_remove.assert_called_once_with("switch.old_total_power")


async def test_c045_still_exposes_one_light_without_auxiliary_controls(hub):
    hub.devices["desk"]["productKey"] = MODEL_C045
    hub.devices["desk"]["effects"] = ["LightMode.Aurora"]
    hub.data["desk"]["effect"] = "LightMode.Aurora"
    entity = light.GlowriumMainLight(hub, "desk")
    assert entity.effect_list == ["Aurora"]
    assert entity.effect == "Aurora"
    await entity.async_turn_on(**{ATTR_EFFECT: "Aurora"})
    assert hub.async_command.await_args_list == [
        call("desk", "set_effect", effect="LightMode.Aurora"),
        call("desk", "turn_on", target="main"),
    ]
