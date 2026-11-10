"""Light entities for Glowrium C017 and C045."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.helpers import entity_registry as er

from . import GlowriumConfigEntry
from .const import DOMAIN, MODEL_C017, MODEL_C045
from .entity import GlowriumEntity

EFFECT_PREFIX = "LightMode."


def display_effect(effect: str) -> str:
    """Hide the protocol namespace in Home Assistant controls."""
    return effect.removeprefix(EFFECT_PREFIX)


async def async_setup_entry(
    hass, entry: GlowriumConfigEntry, async_add_entities
) -> None:
    coordinator = entry.runtime_data

    def factory(hub, device_id):
        if hub.devices[device_id].get("productKey") == MODEL_C017:
            # The auxiliary light is now exposed as a switch and brightness control.
            registry = er.async_get(hass)
            old_entity_id = registry.async_get_entity_id(
                "light", DOMAIN, f"{device_id}_auxiliary_light"
            )
            if old_entity_id:
                registry.async_remove(old_entity_id)
        return [GlowriumMainLight(hub, device_id)]

    coordinator.async_register_entities(entry, async_add_entities, factory)


class GlowriumMainLight(GlowriumEntity, LightEntity):
    """C017 combined light or C045 single light."""

    _attr_name = None
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_min_color_temp_kelvin = 2000
    _attr_max_color_temp_kelvin = 7500

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "main_light")
        self._raw_effects = {
            display_effect(effect): effect for effect in self.device.get("effects", [])
        }
        self._attr_effect_list = list(self._raw_effects)
        if self.device.get("productKey") == MODEL_C045:
            self._attr_supported_color_modes = {ColorMode.HS, ColorMode.COLOR_TEMP}
        else:
            self._attr_supported_color_modes = {ColorMode.COLOR_TEMP}
            self._attr_min_color_temp_kelvin = 2700
            self._attr_max_color_temp_kelvin = 6500

    @property
    def color_mode(self) -> ColorMode:
        if self.device.get("productKey") == MODEL_C017:
            return ColorMode.COLOR_TEMP
        return (
            ColorMode.COLOR_TEMP
            if self.state_data.get("colorMode") == "color_temp"
            else ColorMode.HS
        )

    @property
    def is_on(self) -> bool:
        if self.device.get("productKey") == MODEL_C017:
            return bool(self.state_data.get("power"))
        return bool(self.state_data.get("power"))

    @property
    def brightness(self) -> int:
        return round(int(self.state_data.get("brightness", 0)) * 255 / 100)

    @property
    def color_temp_kelvin(self) -> int | None:
        return self.state_data.get("colorTemperature") or None

    @property
    def hs_color(self) -> tuple[float, float] | None:
        if self.device.get("productKey") != MODEL_C045:
            return None
        return (
            float(self.state_data.get("colorHue", 0)),
            float(self.state_data.get("colorSaturation", 0)) * 100,
        )

    @property
    def effect(self) -> str | None:
        effect = self.state_data.get("effect")
        return display_effect(effect) if isinstance(effect, str) and effect else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        if ATTR_BRIGHTNESS in kwargs:
            await self.async_command(
                "set_brightness", brightness=round(kwargs[ATTR_BRIGHTNESS] * 100 / 255)
            )
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            await self.async_command(
                "set_color_temperature", colorTemperature=kwargs[ATTR_COLOR_TEMP_KELVIN]
            )
        if ATTR_HS_COLOR in kwargs:
            hue, saturation = kwargs[ATTR_HS_COLOR]
            await self.async_command(
                "set_color", hue=hue, saturation=saturation / 100, colorBrightness=1
            )
        if ATTR_EFFECT in kwargs:
            effect = kwargs[ATTR_EFFECT]
            await self.async_command(
                "set_effect", effect=self._raw_effects.get(effect, effect)
            )
        if (
            self.device.get("productKey") == MODEL_C017
            and ATTR_BRIGHTNESS in kwargs
            and not any(
                key in kwargs
                for key in (ATTR_COLOR_TEMP_KELVIN, ATTR_HS_COLOR, ATTR_EFFECT)
            )
        ):
            # A main-brightness change must not switch on the auxiliary channel.
            return
        await self.async_command(
            "turn_on",
            target="all" if self.device.get("productKey") == MODEL_C017 else "main",
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.async_command(
            "turn_off",
            target="all" if self.device.get("productKey") == MODEL_C017 else "main",
        )
