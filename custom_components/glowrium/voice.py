"""English Assist sentences for Glowrium channels, temperature, and effects."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from homeassistant.components.conversation.agent_manager import get_agent_manager
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)

from .bluetooth.profiles import C017_EFFECTS, KELVINS_C045, PRESETS
from .const import DOMAIN, MODEL_C017, MODEL_C045
from .coordinator import GlowriumCoordinator

_LOGGER = logging.getLogger(__name__)
_STEP = 10
_C017_TEMPERATURE_STEP = 500
_MIN_C017_KELVIN = 2700
_MAX_C017_KELVIN = 6500
_ALL_EFFECTS = tuple(sorted(set(C017_EFFECTS) | set(PRESETS["c045"])))
_C045_MUSIC_EFFECTS = {
    effect
    for effect, preset in PRESETS["c045"].items()
    if preset["mode"][:2] == [2, 0]
}
_SENTENCES = {
    "set": [
        "set mood brightness to {0..100:level} percent",
        "set mood brightness to {0..100:level} percent in [the] {area}",
        "set mood brightness to {0..100:level}%",
        "set mood brightness to {0..100:level}% in [the] {area}",
        "set [the] mood light to {0..100:level} percent",
        "set [the] mood light to {0..100:level} percent in [the] {area}",
        "set [the] mood light to {0..100:level}%",
        "set [the] mood light to {0..100:level}% in [the] {area}",
        "set [the] mood light brightness to {0..100:level} percent",
        "set [the] mood light brightness to {0..100:level} percent in [the] {area}",
        "set [the] mood light brightness to {0..100:level}%",
        "set [the] mood light brightness to {0..100:level}% in [the] {area}",
    ],
    "up": [
        "brighten mood channel",
        "brighten mood channel in [the] {area}",
        "brighten mood brightness",
        "brighten mood brightness in [the] {area}",
        "increase mood brightness",
        "increase mood brightness in [the] {area}",
        "brighten [the] mood light",
        "brighten [the] mood light in [the] {area}",
        "increase [the] mood light brightness",
        "increase [the] mood light brightness in [the] {area}",
    ],
    "down": [
        "dim mood channel",
        "dim mood channel in [the] {area}",
        "dim mood brightness",
        "dim mood brightness in [the] {area}",
        "decrease mood brightness",
        "decrease mood brightness in [the] {area}",
        "dim [the] mood light",
        "dim [the] mood light in [the] {area}",
        "decrease [the] mood light brightness",
        "decrease [the] mood light brightness in [the] {area}",
    ],
    "main_set": [
        "set main (level|brightness) to {0..100:level} percent",
        "set main (level|brightness) to {0..100:level} percent in [the] {area}",
        "set main (level|brightness) to {0..100:level}%",
        "set main (level|brightness) to {0..100:level}% in [the] {area}",
        "set [the] main light to {0..100:level} percent",
        "set [the] main light to {0..100:level} percent in [the] {area}",
        "set [the] main light to {0..100:level}%",
        "set [the] main light to {0..100:level}% in [the] {area}",
        "set main light brightness to {0..100:level} percent",
        "set main light brightness to {0..100:level} percent in [the] {area}",
        "set main light brightness to {0..100:level}%",
        "set main light brightness to {0..100:level}% in [the] {area}",
    ],
    "main_up": [
        "brighten [the] main light",
        "brighten [the] main light in [the] {area}",
    ],
    "main_down": [
        "dim [the] main light",
        "dim [the] main light in [the] {area}",
    ],
    "c045_set": [
        "set [the] {device_name} brightness to {0..100:level} percent",
        "set [the] {device_name} brightness to {0..100:level} percent in [the] {area}",
        "set [the] {device_name} brightness to {0..100:level}%",
        "set [the] {device_name} brightness to {0..100:level}% in [the] {area}",
        "set [the] {device_name} light to {0..100:level} percent",
        "set [the] {device_name} light to {0..100:level} percent in [the] {area}",
        "set [the] {device_name} light to {0..100:level}%",
        "set [the] {device_name} light to {0..100:level}% in [the] {area}",
        "set [the] {device_name} light brightness to {0..100:level} percent",
        "set [the] {device_name} light brightness to {0..100:level} percent in [the] {area}",
        "set [the] {device_name} light brightness to {0..100:level}%",
        "set [the] {device_name} light brightness to {0..100:level}% in [the] {area}",
        "set [the] c045 light brightness to {0..100:level} percent",
        "set [the] c045 light brightness to {0..100:level} percent in [the] {area}",
    ],
    "c045_up": [
        "brighten [the] {device_name} light",
        "brighten [the] {device_name} light in [the] {area}",
        "brighten [the] c045 light",
        "brighten [the] c045 light in [the] {area}",
    ],
    "c045_down": [
        "dim [the] {device_name} light",
        "dim [the] {device_name} light in [the] {area}",
        "dim [the] c045 light",
        "dim [the] c045 light in [the] {area}",
    ],
    "speed_set": [
        "set [the] effect speed to {1..100:level} percent",
        "set [the] effect speed to {1..100:level} percent in [the] {area}",
        "set [the] effect speed to {1..100:level}%",
        "set [the] effect speed to {1..100:level}% in [the] {area}",
        "set [the] effect speed to {1..100:level}",
        "set [the] effect speed to {1..100:level} in [the] {area}",
        "set [the] {device_name} effect speed to {1..100:level} percent",
        "set [the] {device_name} effect speed to {1..100:level} percent in [the] {area}",
        "set [the] {device_name} effect speed to {1..100:level}%",
        "set [the] {device_name} effect speed to {1..100:level}% in [the] {area}",
        "set [the] {device_name} effect speed to {1..100:level}",
        "set [the] {device_name} effect speed to {1..100:level} in [the] {area}",
    ],
    "speed_up": [
        "increase [the] effect speed",
        "increase [the] effect speed in [the] {area}",
        "speed up [the] effect",
        "speed up [the] effect in [the] {area}",
        "increase [the] {device_name} effect speed",
        "increase [the] {device_name} effect speed in [the] {area}",
        "speed up [the] {device_name} effect",
        "speed up [the] {device_name} effect in [the] {area}",
    ],
    "speed_down": [
        "decrease [the] effect speed",
        "decrease [the] effect speed in [the] {area}",
        "slow down [the] effect",
        "slow down [the] effect in [the] {area}",
        "decrease [the] {device_name} effect speed",
        "decrease [the] {device_name} effect speed in [the] {area}",
        "slow down [the] {device_name} effect",
        "slow down [the] {device_name} effect in [the] {area}",
    ],
    "main_on": [
        "turn on [the] main light",
        "turn on [the] main light in [the] {area}",
    ],
    "main_off": [
        "turn off [the] main light",
        "turn off [the] main light in [the] {area}",
    ],
    "mood_on": [
        "turn on [the] mood light",
        "turn on [the] mood light in [the] {area}",
    ],
    "mood_off": [
        "turn off [the] mood light",
        "turn off [the] mood light in [the] {area}",
    ],
    "cooler": [
        "set [the] light cooler",
        "set [the] light cooler in [the] {area}",
        "make [the] light cooler",
        "make [the] light cooler in [the] {area}",
    ],
    "warmer": [
        "set [the] light warmer",
        "set [the] light warmer in [the] {area}",
        "make [the] light warmer",
        "make [the] light warmer in [the] {area}",
    ],
}


def _named_sentences(mode: str, sentences: list[str]) -> list[str]:
    """Add a device-name wildcard to the matching channel phrases."""
    if mode.startswith(("c045_", "speed_")):
        return []
    if mode.startswith("main_"):
        replacements = (
            ("main light", "{device_name} main light"),
            ("main (level|brightness)", "{device_name} main (level|brightness)"),
        )
    elif mode in ("set", "up", "down", "mood_on", "mood_off"):
        replacements = (
            ("mood light", "{device_name} mood light"),
            ("mood brightness", "{device_name} mood brightness"),
            ("mood channel", "{device_name} mood channel"),
        )
    else:
        replacements = (
            ("light cooler", "{device_name} cooler"),
            ("light warmer", "{device_name} warmer"),
        )
    named = []
    for sentence in sentences:
        for old, new in replacements:
            if old in sentence:
                named.append(sentence.replace(old, new, 1))
                break
    return named


def _area_id(hass: HomeAssistant, area_name: str) -> str | None:
    """Find an area by its name or voice alias."""
    registry = ar.async_get(hass)
    area = registry.async_get_area_by_name(area_name)
    if area is None:
        aliases = registry.async_get_areas_by_alias(area_name)
        if len(aliases) == 1:
            area = aliases[0]
    return area.id if area is not None else None


def _device_area_id(
    hass: HomeAssistant, device_id: str, channel: str | None = None
) -> str | None:
    """Use the relevant entity's area override, then its device's area."""
    entities = er.async_get(hass)
    if channel == "main_brightness":
        entity_id = entities.async_get_entity_id(
            "light", DOMAIN, f"{device_id}_main_light"
        )
    elif channel:
        entity_id = entities.async_get_entity_id(
            "switch", DOMAIN, f"{device_id}_{channel}_power"
        )
    else:
        entity_id = entities.async_get_entity_id(
            "number", DOMAIN, f"{device_id}_auxiliary_brightness"
        )
    if entity_id:
        entry = entities.async_get(entity_id)
        if entry and entry.area_id:
            return entry.area_id
    for device in dr.async_get(hass).devices.values():
        if (DOMAIN, device_id) in device.identifiers:
            return device.area_id
    return None


def _normalize_name(value: str) -> str:
    """Compare spoken and registered names without case or spacing differences."""
    return " ".join(value.split()).casefold()


def _device_name_matches(
    hass: HomeAssistant,
    coordinator: GlowriumCoordinator,
    device_id: str,
    spoken_name: str,
) -> bool:
    """Accept the catalog name, HA device name, or light entity name/alias."""
    names = {coordinator.devices[device_id].get("name")}
    for device in dr.async_get(hass).devices.values():
        if (DOMAIN, device_id) in device.identifiers:
            names.update(
                (getattr(device, "name", None), getattr(device, "name_by_user", None))
            )

    entities = er.async_get(hass)
    for platform, suffix in (
        ("light", "main_light"),
        ("switch", "main_power"),
        ("switch", "auxiliary_power"),
        ("number", "auxiliary_brightness"),
    ):
        entity_id = entities.async_get_entity_id(
            platform, DOMAIN, f"{device_id}_{suffix}"
        )
        if entity_id and (entry := entities.async_get(entity_id)):
            names.add(entry.name)
            names.update(getattr(entry, "aliases", ()) or ())

    for name in tuple(names):
        if not isinstance(name, str):
            continue
        for suffix in (" main light", " mood light", " mood brightness"):
            if name.casefold().endswith(suffix):
                names.add(name[: -len(suffix)])
    wanted = _normalize_name(spoken_name)
    return bool(wanted) and any(
        isinstance(name, str) and _normalize_name(name) == wanted for name in names
    )


def _spoken_device_name(result: Any) -> str | None:
    """Read the optional device-name wildcard from a matched sentence."""
    match = result.entities.get("device_name")
    if match is None:
        return None
    spoken = str(match.value).strip()
    # Generic light/C045 sentences may also match the name wildcard.
    return None if _normalize_name(spoken) in ("light", "c045") else spoken


def _target_device_id(
    hass: HomeAssistant,
    coordinator: GlowriumCoordinator,
    area_name: str | None,
    channel: str | None = None,
    device_name: str | None = None,
) -> tuple[str | None, str | None]:
    """Never guess which C017 to control if the sentence is ambiguous."""
    area_id = _area_id(hass, area_name) if area_name else None
    if area_name and area_id is None:
        return None, "I couldn't find that room."
    candidates = [
        device_id
        for device_id, device in coordinator.devices.items()
        if device.get("productKey") == MODEL_C017
        and device_id in coordinator.owners
        and (area_id is None or _device_area_id(hass, device_id, channel) == area_id)
        and (
            device_name is None
            or _device_name_matches(hass, coordinator, device_id, device_name)
        )
    ]
    light_name = "Main light" if channel in ("main", "main_brightness") else "Mood light"
    if not candidates:
        return None, f"I couldn't find a C017 {light_name} there."
    if len(candidates) > 1:
        return None, f"More than one C017 {light_name} matches that command."
    return candidates[0], None


def _target_light_device_id(
    hass: HomeAssistant,
    coordinator: GlowriumCoordinator,
    area_name: str | None,
    raw_effect: str | None = None,
    device_name: str | None = None,
    model_filter: str | None = None,
) -> tuple[str | None, str | None]:
    """Select one C017 or C045 light, optionally by supported effect."""
    area_id = _area_id(hass, area_name) if area_name else None
    if area_name and area_id is None:
        return None, "I couldn't find that room."
    candidates = []
    for device_id, device in coordinator.devices.items():
        model = device.get("productKey")
        if model not in (MODEL_C017, MODEL_C045) or device_id not in coordinator.owners:
            continue
        if model_filter is not None and model != model_filter:
            continue
        if area_id is not None and _device_area_id(
            hass, device_id, "main_brightness"
        ) != area_id:
            continue
        if device_name is not None and not _device_name_matches(
            hass, coordinator, device_id, device_name
        ):
            continue
        if raw_effect is not None:
            supported = device.get("effects")
            if supported is None:
                supported = C017_EFFECTS if model == MODEL_C017 else PRESETS["c045"]
            if raw_effect not in supported:
                continue
        candidates.append(device_id)
    if not candidates:
        return None, "I couldn't find a Glowrium light for that command there."
    if len(candidates) > 1:
        return None, "More than one Glowrium light matches that command."
    return candidates[0], None


async def _handle_brightness(
    hass: HomeAssistant,
    coordinator: GlowriumCoordinator,
    result: Any,
    channel: str,
    mode: str,
) -> str:
    """Adjust only the requested C017 channel via the existing command route."""
    area_match = result.entities.get("area")
    area_name = str(area_match.value) if area_match is not None else None
    is_main = channel == "main"
    name = "Main" if is_main else "Mood"
    device_id, error = _target_device_id(
        hass,
        coordinator,
        area_name,
        "main_brightness" if is_main else None,
        _spoken_device_name(result),
    )
    if error:
        return error
    assert device_id is not None

    if mode == "set":
        level_match = result.entities.get("level")
        if level_match is None:
            return f"Please give a {name} brightness from zero to one hundred percent."
        try:
            level = int(level_match.value)
        except (TypeError, ValueError):
            return f"Please give a {name} brightness from zero to one hundred percent."
        if not 0 <= level <= 100:
            return f"Please give a {name} brightness from zero to one hundred percent."
    else:
        state_key = "brightness" if is_main else "auxiliaryBrightness"
        current = coordinator.data.get(device_id, {}).get(state_key)
        if current is None:
            return f"{name} brightness is not available yet."
        try:
            level = int(current)
        except (TypeError, ValueError):
            return f"{name} brightness is not available yet."
        level = max(0, min(100, level + (_STEP if mode == "up" else -_STEP)))

    try:
        await coordinator.async_command(
            device_id, "set_brightness", target=channel, brightness=level
        )
    except HomeAssistantError as err:
        _LOGGER.warning("%s brightness voice command failed: %s", name, err)
        return f"I couldn't change the {name} brightness. Check the light connection."
    return f"{name} brightness set to {level} percent."


async def _handle_mood(
    hass: HomeAssistant,
    coordinator: GlowriumCoordinator,
    result: Any,
    mode: str,
) -> str:
    """Keep Mood brightness on the auxiliary channel."""
    return await _handle_brightness(hass, coordinator, result, "auxiliary", mode)


async def _handle_c045_brightness(
    hass: HomeAssistant,
    coordinator: GlowriumCoordinator,
    result: Any,
    mode: str,
) -> str:
    """Set or step the single C045 light's brightness."""
    area_match = result.entities.get("area")
    area_name = str(area_match.value) if area_match is not None else None
    device_id, error = _target_light_device_id(
        hass,
        coordinator,
        area_name,
        device_name=_spoken_device_name(result),
        model_filter=MODEL_C045,
    )
    if error:
        return error
    assert device_id is not None

    state = coordinator.data.get(device_id, {})
    if state.get("effect") in _C045_MUSIC_EFFECTS:
        return "Brightness is unavailable in this music effect."
    if mode == "set":
        level_match = result.entities.get("level")
        try:
            level = int(level_match.value) if level_match is not None else -1
        except (TypeError, ValueError):
            level = -1
        if not 0 <= level <= 100:
            return "Please give a brightness from zero to one hundred percent."
    else:
        try:
            current = int(state.get("brightness"))
        except (TypeError, ValueError):
            return "The light's brightness is not available yet."
        level = max(0, min(100, current + (_STEP if mode == "up" else -_STEP)))

    try:
        await coordinator.async_command(
            device_id, "set_brightness", target="main", brightness=level
        )
    except HomeAssistantError as err:
        _LOGGER.warning("C045 brightness voice command failed: %s", err)
        return "I couldn't change the light brightness. Check its connection or effect."
    return f"Light brightness set to {level} percent."


async def _handle_effect_speed(
    hass: HomeAssistant,
    coordinator: GlowriumCoordinator,
    result: Any,
    mode: str,
) -> str:
    """Set or step the selected C045 effect speed in percent."""
    area_match = result.entities.get("area")
    area_name = str(area_match.value) if area_match is not None else None
    device_id, error = _target_light_device_id(
        hass,
        coordinator,
        area_name,
        device_name=_spoken_device_name(result),
        model_filter=MODEL_C045,
    )
    if error:
        return error
    assert device_id is not None

    if mode == "set":
        level_match = result.entities.get("level")
        try:
            speed = int(level_match.value) if level_match is not None else -1
        except (TypeError, ValueError):
            speed = -1
        if not 1 <= speed <= 100:
            return "Please give an effect speed from one to one hundred percent."
    else:
        try:
            current = int(coordinator.data.get(device_id, {}).get("effectSpeed"))
        except (TypeError, ValueError):
            return "The effect speed is not available yet."
        if not 1 <= current <= 100:
            return "The effect speed is not available yet."
        speed = max(1, min(100, current + (_STEP if mode == "up" else -_STEP)))

    try:
        await coordinator.async_command(device_id, "set_effect_speed", speed=speed)
    except HomeAssistantError as err:
        _LOGGER.warning("C045 effect speed voice command failed: %s", err)
        if "select an effect" in str(err).casefold():
            return "Select a light effect before changing its speed."
        return "I couldn't change the effect speed. Check the light connection or effect."
    return f"Effect speed set to {speed} percent."


async def _handle_power(
    hass: HomeAssistant,
    coordinator: GlowriumCoordinator,
    result: Any,
    channel: str,
    turn_on: bool,
) -> str:
    """Switch one C017 channel through the existing command route."""
    area_match = result.entities.get("area")
    area_name = str(area_match.value) if area_match is not None else None
    device_id, error = _target_device_id(
        hass, coordinator, area_name, channel, _spoken_device_name(result)
    )
    if error:
        return error
    assert device_id is not None

    light_name = "Main light" if channel == "main" else "Mood light"
    try:
        await coordinator.async_command(
            device_id, "turn_on" if turn_on else "turn_off", target=channel
        )
    except HomeAssistantError as err:
        _LOGGER.warning("%s voice command failed: %s", light_name, err)
        return f"I couldn't change the {light_name}. Check the light connection."
    return f"{light_name} turned {'on' if turn_on else 'off'}."


async def _handle_temperature(
    hass: HomeAssistant,
    coordinator: GlowriumCoordinator,
    result: Any,
    direction: str,
) -> str:
    """Step C017 by 500 K or C045 to its adjacent fixed preset."""
    area_match = result.entities.get("area")
    area_name = str(area_match.value) if area_match is not None else None
    device_id, error = _target_light_device_id(
        hass, coordinator, area_name, device_name=_spoken_device_name(result)
    )
    if error:
        return error
    assert device_id is not None

    try:
        current = int(coordinator.data.get(device_id, {}).get("colorTemperature"))
    except (TypeError, ValueError):
        return "The light's color temperature is not available yet."
    model = coordinator.devices[device_id].get("productKey")
    minimum = _MIN_C017_KELVIN if model == MODEL_C017 else KELVINS_C045[0]
    maximum = _MAX_C017_KELVIN if model == MODEL_C017 else KELVINS_C045[-1]
    if not minimum <= current <= maximum:
        return "The light's color temperature is not available yet."
    if model == MODEL_C045:
        if direction == "cooler":
            kelvin = next(
                (preset for preset in KELVINS_C045 if preset > current), maximum
            )
        else:
            kelvin = next(
                (preset for preset in reversed(KELVINS_C045) if preset < current),
                minimum,
            )
    else:
        change = (
            _C017_TEMPERATURE_STEP
            if direction == "cooler"
            else -_C017_TEMPERATURE_STEP
        )
        kelvin = max(minimum, min(maximum, current + change))
    if kelvin == current:
        return f"The light is already at {kelvin} Kelvin."

    try:
        await coordinator.async_command(
            device_id, "set_color_temperature", colorTemperature=kelvin
        )
    except HomeAssistantError as err:
        _LOGGER.warning("Color temperature voice command failed: %s", err)
        return "I couldn't change the light's color temperature. Check its connection or effect."
    return f"Color temperature set to {kelvin} Kelvin."


def _effect_sentences(raw_effect: str) -> list[str]:
    """Use literal effect names so Assist needs no separate effect slot list."""
    label = raw_effect.removeprefix("LightMode.")
    spoken = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", label).lower()
    aliases = sorted({label.lower(), spoken})
    return [
        sentence
        for alias in aliases
        for sentence in (
            f"set [the] light (mode|effect) to {alias}",
            f"set [the] light (mode|effect) to {alias} in [the] {{area}}",
            f"set [the] {{device_name}} (mode|effect) to {alias}",
            f"set [the] {{device_name}} (mode|effect) to {alias} in [the] {{area}}",
        )
    ]


async def _handle_effect(
    hass: HomeAssistant,
    coordinator: GlowriumCoordinator,
    result: Any,
    raw_effect: str,
) -> str:
    """Apply an effect supported by the selected C017 or C045."""
    area_match = result.entities.get("area")
    area_name = str(area_match.value) if area_match is not None else None
    device_id, error = _target_light_device_id(
        hass, coordinator, area_name, raw_effect, _spoken_device_name(result)
    )
    if error:
        return error
    assert device_id is not None

    try:
        await coordinator.async_command(device_id, "set_effect", effect=raw_effect)
    except HomeAssistantError as err:
        _LOGGER.warning("Effect voice command failed: %s", err)
        return "I couldn't change the light effect. Check the light connection."
    return f"Light effect set to {raw_effect.removeprefix('LightMode.')}."


def register_voice_commands(
    hass: HomeAssistant, coordinator: GlowriumCoordinator
) -> Callable[[], None]:
    """Register brand-free sentences once for all Glowrium config entries."""
    manager = get_agent_manager(hass)
    unsubscribers: list[Callable[[], None]] = []
    try:
        for mode, sentences in _SENTENCES.items():

            async def handle(_user_input, result, mode=mode):
                if mode in ("set", "up", "down"):
                    return await _handle_mood(hass, coordinator, result, mode)
                if mode in ("main_set", "main_up", "main_down"):
                    return await _handle_brightness(
                        hass, coordinator, result, "main", mode.removeprefix("main_")
                    )
                if mode in ("c045_set", "c045_up", "c045_down"):
                    return await _handle_c045_brightness(
                        hass, coordinator, result, mode.removeprefix("c045_")
                    )
                if mode in ("speed_set", "speed_up", "speed_down"):
                    return await _handle_effect_speed(
                        hass, coordinator, result, mode.removeprefix("speed_")
                    )
                if mode in ("cooler", "warmer"):
                    return await _handle_temperature(hass, coordinator, result, mode)
                channel, action = mode.split("_", 1)
                return await _handle_power(
                    hass,
                    coordinator,
                    result,
                    "auxiliary" if channel == "mood" else "main",
                    action == "on",
                )

            unsubscribers.append(
                manager.register_trigger(
                    sentences=[*sentences, *_named_sentences(mode, sentences)],
                    trigger_callback=handle,
                )
            )
        for raw_effect in _ALL_EFFECTS:

            async def handle_effect(_user_input, result, effect=raw_effect):
                return await _handle_effect(hass, coordinator, result, effect)

            unsubscribers.append(
                manager.register_trigger(
                    sentences=_effect_sentences(raw_effect),
                    trigger_callback=handle_effect,
                )
            )
    except Exception:
        for unsubscribe in unsubscribers:
            unsubscribe()
        raise

    def unsubscribe_all() -> None:
        for unsubscribe in unsubscribers:
            unsubscribe()

    return unsubscribe_all
