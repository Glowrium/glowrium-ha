"""C017 Assist commands target the requested channel only."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.glowrium import voice
from custom_components.glowrium.bluetooth.profiles import C017_EFFECTS, PRESETS
from custom_components.glowrium.const import DOMAIN, MODEL_C017, MODEL_C045


def _result(**slots):
    return SimpleNamespace(
        entities={key: SimpleNamespace(value=value) for key, value in slots.items()}
    )


def _one_c017(hub):
    hub.devices["desk"] = {
        "productKey": MODEL_C017,
        "effects": list(C017_EFFECTS),
    }
    hub.owners["desk"] = "local"
    hub.data["desk"] = {
        "online": True,
        "brightness": 50,
        "auxiliaryBrightness": 50,
        "colorTemperature": 3500,
    }
    hub.async_command = AsyncMock()


def _one_c045(hub):
    hub.devices["desk"] = {
        "productKey": MODEL_C045,
        "effects": list(PRESETS["c045"]),
    }
    hub.owners["desk"] = "local"
    hub.data["desk"] = {
        "online": True,
        "brightness": 50,
        "colorTemperature": 5000,
    }
    hub.async_command = AsyncMock()


@pytest.mark.asyncio
async def test_mood_voice_sets_and_steps_only_auxiliary(hass, hub):
    _one_c017(hub)

    assert await voice._handle_mood(hass, hub, _result(level=10), "set") == (
        "Mood brightness set to 10 percent."
    )
    hub.async_command.assert_awaited_with(
        "desk", "set_brightness", target="auxiliary", brightness=10
    )

    await voice._handle_mood(hass, hub, _result(), "up")
    hub.async_command.assert_awaited_with(
        "desk", "set_brightness", target="auxiliary", brightness=60
    )
    await voice._handle_mood(hass, hub, _result(), "down")
    hub.async_command.assert_awaited_with(
        "desk", "set_brightness", target="auxiliary", brightness=40
    )


@pytest.mark.asyncio
async def test_mood_voice_clamps_and_rejects_missing_state(hass, hub):
    _one_c017(hub)
    hub.data["desk"]["auxiliaryBrightness"] = 98
    await voice._handle_mood(hass, hub, _result(), "up")
    hub.async_command.assert_awaited_with(
        "desk", "set_brightness", target="auxiliary", brightness=100
    )
    hub.data["desk"]["auxiliaryBrightness"] = 2
    await voice._handle_mood(hass, hub, _result(), "down")
    hub.async_command.assert_awaited_with(
        "desk", "set_brightness", target="auxiliary", brightness=0
    )
    hub.data["desk"].pop("auxiliaryBrightness")
    hub.async_command.reset_mock()
    assert "not available" in await voice._handle_mood(hass, hub, _result(), "up")
    hub.async_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_mood_voice_never_guesses_among_multiple_c017s(hass, hub):
    _one_c017(hub)
    hub.devices["desk2"] = {"productKey": MODEL_C017}
    hub.owners["desk2"] = "local2"
    hub.data["desk2"] = {"online": True, "auxiliaryBrightness": 20}
    response = await voice._handle_mood(hass, hub, _result(level=25), "set")
    assert "More than one" in response
    hub.async_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_main_brightness_voice_sets_and_steps_only_main(hass, hub):
    _one_c017(hub)

    response = await voice._handle_brightness(
        hass, hub, _result(level=25), "main", "set"
    )
    assert response == "Main brightness set to 25 percent."
    hub.async_command.assert_awaited_with(
        "desk", "set_brightness", target="main", brightness=25
    )

    await voice._handle_brightness(hass, hub, _result(), "main", "up")
    hub.async_command.assert_awaited_with(
        "desk", "set_brightness", target="main", brightness=60
    )
    await voice._handle_brightness(hass, hub, _result(), "main", "down")
    hub.async_command.assert_awaited_with(
        "desk", "set_brightness", target="main", brightness=40
    )


@pytest.mark.asyncio
async def test_main_brightness_voice_does_not_guess_among_devices(hass, hub):
    _one_c017(hub)
    hub.devices["desk2"] = {"productKey": MODEL_C017}
    hub.owners["desk2"] = "local2"
    hub.data["desk2"] = {"online": True, "brightness": 20}
    response = await voice._handle_brightness(
        hass, hub, _result(level=25), "main", "set"
    )
    assert "More than one" in response
    hub.async_command.assert_not_awaited()


def test_main_brightness_uses_light_entity_area_override(hass, monkeypatch):
    entities = MagicMock()
    entities.async_get_entity_id.return_value = "light.desk"
    entities.async_get.return_value = SimpleNamespace(area_id="living")
    monkeypatch.setattr(voice.er, "async_get", lambda hass: entities)

    assert voice._device_area_id(hass, "desk", "main_brightness") == "living"
    entities.async_get_entity_id.assert_called_once_with(
        "light", DOMAIN, "desk_main_light"
    )


@pytest.mark.asyncio
async def test_power_voice_switches_only_the_requested_channel(hass, hub):
    _one_c017(hub)
    for channel in ("main", "auxiliary"):
        for turn_on in (True, False):
            response = await voice._handle_power(
                hass, hub, _result(), channel, turn_on
            )
            expected = "turned on" if turn_on else "turned off"
            assert expected in response
            hub.async_command.assert_awaited_with(
                "desk", "turn_on" if turn_on else "turn_off", target=channel
            )


@pytest.mark.asyncio
async def test_power_voice_uses_area_and_rejects_ambiguous_targets(
    hass, hub, monkeypatch
):
    _one_c017(hub)
    hub.devices["desk2"] = {"productKey": MODEL_C017}
    hub.owners["desk2"] = "local2"
    hub.data["desk2"] = {"online": True}

    response = await voice._handle_power(hass, hub, _result(), "main", True)
    assert "More than one" in response
    hub.async_command.assert_not_awaited()

    monkeypatch.setattr(voice, "_area_id", lambda hass, name: "living")
    monkeypatch.setattr(
        voice, "_device_area_id", lambda hass, device_id, channel: (
            "living" if device_id == "desk2" else "study"
        )
    )
    await voice._handle_power(hass, hub, _result(area="living room"), "auxiliary", False)
    hub.async_command.assert_awaited_once_with(
        "desk2", "turn_off", target="auxiliary"
    )


@pytest.mark.asyncio
async def test_temperature_voice_steps_and_clamps_c017(hass, hub):
    _one_c017(hub)
    response = await voice._handle_temperature(hass, hub, _result(), "cooler")
    assert response == "Color temperature set to 4000 Kelvin."
    hub.async_command.assert_awaited_with(
        "desk", "set_color_temperature", colorTemperature=4000
    )

    response = await voice._handle_temperature(hass, hub, _result(), "warmer")
    assert response == "Color temperature set to 3000 Kelvin."
    hub.async_command.assert_awaited_with(
        "desk", "set_color_temperature", colorTemperature=3000
    )

    hub.data["desk"]["colorTemperature"] = 6300
    await voice._handle_temperature(hass, hub, _result(), "cooler")
    hub.async_command.assert_awaited_with(
        "desk", "set_color_temperature", colorTemperature=6500
    )
    hub.data["desk"]["colorTemperature"] = 2900
    await voice._handle_temperature(hass, hub, _result(), "warmer")
    hub.async_command.assert_awaited_with(
        "desk", "set_color_temperature", colorTemperature=2700
    )

    hub.data["desk"]["colorTemperature"] = 6500
    hub.async_command.reset_mock()
    assert "already" in await voice._handle_temperature(
        hass, hub, _result(), "cooler"
    )
    hub.async_command.assert_not_awaited()

    hub.data["desk"].pop("colorTemperature")
    assert "not available" in await voice._handle_temperature(
        hass, hub, _result(), "warmer"
    )
    hub.async_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_temperature_voice_moves_to_adjacent_c045_preset(hass, hub):
    _one_c045(hub)
    response = await voice._handle_temperature(hass, hub, _result(), "cooler")
    assert response == "Color temperature set to 6500 Kelvin."
    hub.async_command.assert_awaited_with(
        "desk", "set_color_temperature", colorTemperature=6500
    )

    response = await voice._handle_temperature(hass, hub, _result(), "warmer")
    assert response == "Color temperature set to 4000 Kelvin."
    hub.async_command.assert_awaited_with(
        "desk", "set_color_temperature", colorTemperature=4000
    )

    hub.data["desk"]["colorTemperature"] = 3500
    await voice._handle_temperature(hass, hub, _result(), "cooler")
    hub.async_command.assert_awaited_with(
        "desk", "set_color_temperature", colorTemperature=4000
    )
    await voice._handle_temperature(hass, hub, _result(), "warmer")
    hub.async_command.assert_awaited_with(
        "desk", "set_color_temperature", colorTemperature=2700
    )

    hub.data["desk"]["colorTemperature"] = 7500
    hub.async_command.reset_mock()
    assert "already" in await voice._handle_temperature(
        hass, hub, _result(), "cooler"
    )
    hub.async_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_c045_brightness_voice_sets_and_steps(hass, hub):
    _one_c045(hub)
    response = await voice._handle_c045_brightness(
        hass, hub, _result(level=25), "set"
    )
    assert response == "Light brightness set to 25 percent."
    hub.async_command.assert_awaited_with(
        "desk", "set_brightness", target="main", brightness=25
    )
    await voice._handle_c045_brightness(hass, hub, _result(), "up")
    hub.async_command.assert_awaited_with(
        "desk", "set_brightness", target="main", brightness=60
    )
    await voice._handle_c045_brightness(hass, hub, _result(), "down")
    hub.async_command.assert_awaited_with(
        "desk", "set_brightness", target="main", brightness=40
    )

    hub.data["desk"]["brightness"] = 98
    await voice._handle_c045_brightness(hass, hub, _result(), "up")
    hub.async_command.assert_awaited_with(
        "desk", "set_brightness", target="main", brightness=100
    )
    hub.data["desk"]["brightness"] = 2
    await voice._handle_c045_brightness(hass, hub, _result(), "down")
    hub.async_command.assert_awaited_with(
        "desk", "set_brightness", target="main", brightness=0
    )


@pytest.mark.asyncio
async def test_c045_brightness_voice_rejects_music_effect_and_missing_state(hass, hub):
    _one_c045(hub)
    hub.data["desk"]["effect"] = "LightMode.RhythmFlow"
    assert "music effect" in await voice._handle_c045_brightness(
        hass, hub, _result(level=30), "set"
    )
    hub.async_command.assert_not_awaited()

    hub.data["desk"].pop("effect")
    hub.data["desk"].pop("brightness")
    assert "not available" in await voice._handle_c045_brightness(
        hass, hub, _result(), "up"
    )
    hub.async_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_c045_brightness_voice_selects_named_device(hass, hub, monkeypatch):
    _one_c045(hub)
    hub.devices["desk"]["name"] = "Tom"
    hub.devices["other"] = {"productKey": MODEL_C045, "name": "Jerry"}
    hub.owners["other"] = "local2"
    hub.data["other"] = {"online": True, "brightness": 20}
    monkeypatch.setattr(
        voice.dr, "async_get", lambda hass: SimpleNamespace(devices={})
    )
    monkeypatch.setattr(
        voice.er,
        "async_get",
        lambda hass: SimpleNamespace(
            async_get_entity_id=MagicMock(return_value=None)
        ),
    )

    await voice._handle_c045_brightness(
        hass, hub, _result(device_name="tom", level=35), "set"
    )
    hub.async_command.assert_awaited_once_with(
        "desk", "set_brightness", target="main", brightness=35
    )
    hub.async_command.reset_mock()
    assert "More than one" in await voice._handle_c045_brightness(
        hass, hub, _result(), "up"
    )
    hub.async_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_c045_brightness_voice_never_controls_c017(hass, hub):
    _one_c017(hub)
    assert "couldn't find" in await voice._handle_c045_brightness(
        hass, hub, _result(level=30), "set"
    )
    hub.async_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_c045_effect_speed_voice_sets_steps_and_clamps(hass, hub):
    _one_c045(hub)
    hub.data["desk"]["effectSpeed"] = 50

    assert await voice._handle_effect_speed(hass, hub, _result(level=25), "set") == (
        "Effect speed set to 25 percent."
    )
    hub.async_command.assert_awaited_with("desk", "set_effect_speed", speed=25)
    await voice._handle_effect_speed(hass, hub, _result(), "up")
    hub.async_command.assert_awaited_with("desk", "set_effect_speed", speed=60)
    await voice._handle_effect_speed(hass, hub, _result(), "down")
    hub.async_command.assert_awaited_with("desk", "set_effect_speed", speed=40)

    hub.data["desk"]["effectSpeed"] = 98
    await voice._handle_effect_speed(hass, hub, _result(), "up")
    hub.async_command.assert_awaited_with("desk", "set_effect_speed", speed=100)
    hub.data["desk"]["effectSpeed"] = 3
    await voice._handle_effect_speed(hass, hub, _result(), "down")
    hub.async_command.assert_awaited_with("desk", "set_effect_speed", speed=1)


@pytest.mark.asyncio
async def test_c045_effect_speed_voice_checks_target_and_state(hass, hub, monkeypatch):
    _one_c045(hub)
    hub.devices["desk"]["name"] = "Tom"
    hub.devices["other"] = {"productKey": MODEL_C045, "name": "Jerry"}
    hub.owners["other"] = "local2"
    hub.data["other"] = {"effectSpeed": 30}
    monkeypatch.setattr(voice.dr, "async_get", lambda hass: SimpleNamespace(devices={}))
    monkeypatch.setattr(
        voice.er,
        "async_get",
        lambda hass: SimpleNamespace(async_get_entity_id=MagicMock(return_value=None)),
    )

    assert "More than one" in await voice._handle_effect_speed(
        hass, hub, _result(level=30), "set"
    )
    hub.async_command.assert_not_awaited()
    assert await voice._handle_effect_speed(
        hass, hub, _result(device_name="Tom", level=30), "set"
    ) == "Effect speed set to 30 percent."
    hub.async_command.assert_awaited_once_with("desk", "set_effect_speed", speed=30)

    hub.async_command.reset_mock()
    assert "not available" in await voice._handle_effect_speed(
        hass, hub, _result(device_name="Tom"), "up"
    )
    assert "one to one hundred" in await voice._handle_effect_speed(
        hass, hub, _result(device_name="Tom", level=0), "set"
    )
    hub.async_command.assert_not_awaited()

    hub.async_command.side_effect = HomeAssistantError(
        "Select an effect before adjusting its speed"
    )
    assert "Select a light effect" in await voice._handle_effect_speed(
        hass, hub, _result(device_name="Tom", level=30), "set"
    )


@pytest.mark.asyncio
async def test_c045_effect_speed_voice_never_controls_c017(hass, hub):
    _one_c017(hub)
    assert "couldn't find" in await voice._handle_effect_speed(
        hass, hub, _result(level=30), "set"
    )
    hub.async_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_effect_voice_uses_raw_protocol_name_and_checks_availability(hass, hub):
    _one_c017(hub)
    response = await voice._handle_effect(
        hass, hub, _result(), "LightMode.Reading"
    )
    assert response == "Light effect set to Reading."
    hub.async_command.assert_awaited_once_with(
        "desk", "set_effect", effect="LightMode.Reading"
    )

    hub.devices["desk"]["effects"] = ["LightMode.Relax"]
    hub.async_command.reset_mock()
    assert "couldn't find" in await voice._handle_effect(
        hass, hub, _result(), "LightMode.Reading"
    )
    hub.async_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_c045_effect_voice_selects_supported_device(hass, hub):
    _one_c017(hub)
    hub.devices["other"] = {
        "productKey": MODEL_C045,
        "effects": list(PRESETS["c045"]),
    }
    hub.owners["other"] = "local2"
    hub.data["other"] = {"online": True}
    response = await voice._handle_effect(hass, hub, _result(), "LightMode.Aurora")
    assert response == "Light effect set to Aurora."
    hub.async_command.assert_awaited_once_with(
        "other", "set_effect", effect="LightMode.Aurora"
    )


@pytest.mark.asyncio
async def test_temperature_voice_rejects_multiple_lights(hass, hub):
    _one_c017(hub)
    hub.devices["other"] = {"productKey": MODEL_C045}
    hub.owners["other"] = "local2"
    hub.data["other"] = {"online": True, "colorTemperature": 4000}
    response = await voice._handle_temperature(hass, hub, _result(), "cooler")
    assert "More than one" in response
    hub.async_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_named_voice_commands_select_tom(hass, hub, monkeypatch):
    _one_c017(hub)
    hub.devices["desk"]["name"] = "Tom"
    hub.devices["other"] = {
        "productKey": MODEL_C017,
        "name": "Jerry",
        "effects": list(C017_EFFECTS),
    }
    hub.owners["other"] = "local2"
    hub.data["other"] = {
        "online": True,
        "brightness": 20,
        "auxiliaryBrightness": 20,
        "colorTemperature": 4000,
    }
    monkeypatch.setattr(
        voice.dr, "async_get", lambda hass: SimpleNamespace(devices={})
    )
    monkeypatch.setattr(
        voice.er,
        "async_get",
        lambda hass: SimpleNamespace(
            async_get_entity_id=MagicMock(return_value=None)
        ),
    )
    named = _result(device_name="tOm")

    await voice._handle_brightness(hass, hub, named, "main", "up")
    hub.async_command.assert_awaited_with(
        "desk", "set_brightness", target="main", brightness=60
    )
    await voice._handle_brightness(hass, hub, named, "main", "down")
    hub.async_command.assert_awaited_with(
        "desk", "set_brightness", target="main", brightness=40
    )
    await voice._handle_brightness(
        hass, hub, _result(device_name="Tom", level=10), "auxiliary", "set"
    )
    hub.async_command.assert_awaited_with(
        "desk", "set_brightness", target="auxiliary", brightness=10
    )
    await voice._handle_brightness(hass, hub, named, "auxiliary", "up")
    hub.async_command.assert_awaited_with(
        "desk", "set_brightness", target="auxiliary", brightness=60
    )
    await voice._handle_brightness(hass, hub, named, "auxiliary", "down")
    hub.async_command.assert_awaited_with(
        "desk", "set_brightness", target="auxiliary", brightness=40
    )
    await voice._handle_temperature(hass, hub, named, "cooler")
    hub.async_command.assert_awaited_with(
        "desk", "set_color_temperature", colorTemperature=4000
    )
    await voice._handle_temperature(hass, hub, named, "warmer")
    hub.async_command.assert_awaited_with(
        "desk", "set_color_temperature", colorTemperature=3000
    )
    await voice._handle_effect(hass, hub, named, "LightMode.Reading")
    hub.async_command.assert_awaited_with(
        "desk", "set_effect", effect="LightMode.Reading"
    )
    await voice._handle_power(hass, hub, named, "main", True)
    hub.async_command.assert_awaited_with("desk", "turn_on", target="main")
    await voice._handle_power(hass, hub, named, "auxiliary", False)
    hub.async_command.assert_awaited_with("desk", "turn_off", target="auxiliary")

    hub.async_command.reset_mock()
    assert "couldn't find" in await voice._handle_temperature(
        hass, hub, _result(device_name="Unknown"), "cooler"
    )
    hub.async_command.assert_not_awaited()

    monkeypatch.setattr(voice, "_area_id", lambda hass, name: "living")
    monkeypatch.setattr(
        voice, "_device_area_id", lambda hass, device_id, channel: "living"
    )
    await voice._handle_temperature(
        hass, hub, _result(device_name="Tom", area="living room"), "cooler"
    )
    hub.async_command.assert_awaited_once_with(
        "desk", "set_color_temperature", colorTemperature=4000
    )

    hub.devices["other"]["name"] = "Tom"
    hub.async_command.reset_mock()
    assert "More than one" in await voice._handle_temperature(
        hass, hub, _result(device_name="Tom", area="living room"), "cooler"
    )
    hub.async_command.assert_not_awaited()


def test_named_voice_uses_ha_device_rename(hass, hub, monkeypatch):
    _one_c017(hub)
    hub.devices["desk"]["name"] = "Original"
    device = SimpleNamespace(
        identifiers={(DOMAIN, "desk")}, name="Original", name_by_user="Tom"
    )
    monkeypatch.setattr(
        voice.dr, "async_get", lambda hass: SimpleNamespace(devices={"desk": device})
    )
    monkeypatch.setattr(
        voice.er,
        "async_get",
        lambda hass: SimpleNamespace(
            async_get_entity_id=MagicMock(return_value=None)
        ),
    )
    assert voice._device_name_matches(hass, hub, "desk", "tom")


def test_generic_light_sentence_does_not_treat_light_as_device_name():
    assert voice._spoken_device_name(_result(device_name="light")) is None
    assert voice._spoken_device_name(_result(device_name="C045")) is None
    assert voice._spoken_device_name(_result(device_name="Tom")) == "Tom"


def test_voice_registers_brand_free_sentences(hass, hub, monkeypatch):
    manager = SimpleNamespace(register_trigger=MagicMock())
    trigger_count = len(voice._SENTENCES) + len(voice._ALL_EFFECTS)
    unsubscribers = [MagicMock() for _ in range(trigger_count)]
    manager.register_trigger.side_effect = unsubscribers
    monkeypatch.setattr(voice, "get_agent_manager", lambda hass: manager)

    unregister = voice.register_voice_commands(hass, hub)
    assert manager.register_trigger.call_count == trigger_count
    commands = [
        sentence
        for call in manager.register_trigger.call_args_list
        for sentence in call.kwargs["sentences"]
    ]
    assert all("glowrium" not in sentence.lower() for sentence in commands)
    assert any("{0..100:level} percent" in sentence for sentence in commands)
    assert any("{0..100:level}%" in sentence for sentence in commands)
    assert "turn on [the] main light in [the] {area}" in commands
    assert "turn off [the] mood light" in commands
    assert "set main light brightness to {0..100:level} percent" in commands
    assert "brighten [the] main light" in commands
    assert (
        "set [the] mood light to {0..100:level} percent in [the] {area}"
        in commands
    )
    assert "set [the] mood light to {0..100:level}%" in commands
    assert "set mood brightness to {0..100:level} percent" in commands
    assert "set mood brightness to {0..100:level}% in [the] {area}" in commands
    assert "brighten mood brightness" in commands
    assert "increase [the] mood light brightness" in commands
    assert "dim mood brightness" in commands
    assert "decrease [the] mood light brightness" in commands
    assert not any("mood (level|brightness)" in sentence for sentence in commands)
    assert "set [the] light cooler in [the] {area}" in commands
    assert "set [the] light warmer in [the] {area}" in commands
    assert "set [the] light (mode|effect) to reading in [the] {area}" in commands
    assert "set [the] light (mode|effect) to happy therapy" in commands
    assert "set [the] light (mode|effect) to aurora" in commands
    assert "brighten [the] {device_name} main light" in commands
    assert "dim [the] {device_name} mood light" in commands
    assert (
        "set [the] {device_name} mood light to {0..100:level} percent"
        in commands
    )
    assert "set [the] {device_name} cooler" in commands
    assert "set [the] {device_name} warmer" in commands
    assert "set [the] {device_name} (mode|effect) to reading" in commands
    assert (
        "set [the] {device_name} (mode|effect) to reading in [the] {area}"
        in commands
    )
    assert "set [the] {device_name} cooler in [the] {area}" in commands
    assert "set [the] {device_name} light brightness to {0..100:level} percent" in commands
    assert "brighten [the] {device_name} light" in commands
    assert "dim [the] {device_name} light in [the] {area}" in commands
    assert "set [the] c045 light brightness to {0..100:level} percent" in commands
    assert "set [the] effect speed to {1..100:level} percent in [the] {area}" in commands
    assert "set [the] {device_name} effect speed to {1..100:level}%" in commands
    assert "set [the] effect speed to {1..100:level}" in commands
    assert "set [the] {device_name} effect speed to {1..100:level} in [the] {area}" in commands
    assert "increase [the] {device_name} effect speed in [the] {area}" in commands
    assert "decrease [the] effect speed" in commands
    assert "speed up [the] {device_name} effect" in commands
    assert "slow down [the] effect in [the] {area}" in commands
    assert "turn on [the] {device_name} main light" in commands
    unregister()
    for unsubscribe in unsubscribers:
        unsubscribe.assert_called_once_with()


@pytest.mark.asyncio
async def test_mood_light_sentence_routes_to_auxiliary(hass, hub, monkeypatch):
    _one_c017(hub)
    manager = SimpleNamespace(register_trigger=MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(voice, "get_agent_manager", lambda hass: manager)
    unregister = voice.register_voice_commands(hass, hub)

    set_trigger = manager.register_trigger.call_args_list[0]
    assert "set [the] mood light to {0..100:level} percent" in set_trigger.kwargs[
        "sentences"
    ]
    assert "set mood brightness to {0..100:level} percent" in set_trigger.kwargs[
        "sentences"
    ]
    response = await set_trigger.kwargs["trigger_callback"](
        None, _result(level=10)
    )
    assert response == "Mood brightness set to 10 percent."
    hub.async_command.assert_awaited_once_with(
        "desk", "set_brightness", target="auxiliary", brightness=10
    )
    hub.async_command.reset_mock()
    response = await set_trigger.kwargs["trigger_callback"](
        None, _result(level=20)
    )
    assert response == "Mood brightness set to 20 percent."
    hub.async_command.assert_awaited_once_with(
        "desk", "set_brightness", target="auxiliary", brightness=20
    )
    unregister()
