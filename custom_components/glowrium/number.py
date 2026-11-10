"""Number entities for Glowrium."""

from homeassistant.components.number import NumberEntity, NumberMode

from . import GlowriumConfigEntry
from .const import MODEL_C017, MODEL_C045
from .entity import GlowriumEntity


async def async_setup_entry(
    hass, entry: GlowriumConfigEntry, async_add_entities
) -> None:
    coordinator = entry.runtime_data

    def factory(hub, device_id):
        model = hub.devices[device_id].get("productKey")
        if model == MODEL_C017:
            return [GlowriumAuxiliaryBrightness(hub, device_id)]
        if model == MODEL_C045:
            return [GlowriumEffectSpeed(hub, device_id)]
        return []

    coordinator.async_register_entities(
        entry, async_add_entities, factory
    )


class GlowriumAuxiliaryBrightness(GlowriumEntity, NumberEntity):
    """C017 auxiliary channel brightness in percent."""

    _attr_name = "Mood brightness"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "auxiliary_brightness")

    @property
    def native_value(self) -> float:
        return float(self.state_data.get("auxiliaryBrightness", 0))

    async def async_set_native_value(self, value: float) -> None:
        await self.async_command(
            "set_brightness", target="auxiliary", brightness=round(value)
        )


class GlowriumEffectSpeed(GlowriumEntity, NumberEntity):
    """C045 dynamic effect speed."""

    _attr_name = "Effect speed"
    _attr_native_min_value = 1
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "effect_speed")

    @property
    def native_value(self) -> float:
        return float(self.state_data.get("effectSpeed", 1))

    async def async_set_native_value(self, value: float) -> None:
        await self.async_command("set_effect_speed", speed=round(value))
