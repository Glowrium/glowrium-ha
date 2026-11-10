"""Switch entities for Glowrium."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers import entity_registry as er

from . import GlowriumConfigEntry
from .const import DOMAIN, MODEL_C017
from .entity import GlowriumEntity


async def async_setup_entry(
    hass, entry: GlowriumConfigEntry, async_add_entities
) -> None:
    coordinator = entry.runtime_data

    def factory(hub, device_id):
        if hub.devices[device_id].get("productKey") != MODEL_C017:
            return []
        registry = er.async_get(hass)
        old_entity_id = registry.async_get_entity_id(
            "switch", DOMAIN, f"{device_id}_total_power"
        )
        if old_entity_id:
            registry.async_remove(old_entity_id)
        return [
            GlowriumMainPowerSwitch(hub, device_id),
            GlowriumAuxiliaryPowerSwitch(hub, device_id),
            GlowriumRhythmSwitch(hub, device_id),
        ]

    coordinator.async_register_entities(
        entry, async_add_entities, factory
    )


class GlowriumPowerSwitch(GlowriumEntity, SwitchEntity):
    """One C017 power channel backed by the shared command route."""

    _target: str
    _state_key: str
    _suffix: str

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, self._suffix)

    @property
    def is_on(self) -> bool:
        return bool(self.state_data.get(self._state_key))

    async def async_turn_on(self, **kwargs) -> None:
        await self.async_command("turn_on", target=self._target)

    async def async_turn_off(self, **kwargs) -> None:
        await self.async_command("turn_off", target=self._target)


class GlowriumMainPowerSwitch(GlowriumPowerSwitch):
    """Switch the C017 main channel only."""

    _attr_name = "Main light"
    _target = "main"
    _state_key = "mainPower"
    _suffix = "main_power"


class GlowriumAuxiliaryPowerSwitch(GlowriumPowerSwitch):
    """Switch the C017 auxiliary channel only."""

    _attr_name = "Mood light"
    _target = "auxiliary"
    _state_key = "auxiliaryPower"
    _suffix = "auxiliary_power"


class GlowriumRhythmSwitch(GlowriumEntity, SwitchEntity):
    """C017 circadian rhythm switch."""

    _attr_name = "Circadian rhythm"

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "rhythm")

    @property
    def is_on(self) -> bool:
        return bool(self.state_data.get("rhythm"))

    async def async_turn_on(self, **kwargs) -> None:
        await self.async_command("set_rhythm", power=True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.async_command("set_rhythm", power=False)
