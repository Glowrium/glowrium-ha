"""Binary sensors for Glowrium."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from . import GlowriumConfigEntry
from .entity import GlowriumEntity


async def async_setup_entry(
    hass, entry: GlowriumConfigEntry, async_add_entities
) -> None:
    coordinator = entry.runtime_data
    coordinator.async_register_entities(
        entry,
        async_add_entities,
        lambda hub, device_id: [GlowriumOnlineSensor(hub, device_id)],
    )


class GlowriumOnlineSensor(GlowriumEntity, BinarySensorEntity):
    """Device connectivity through either configured transport."""

    _attr_name = "Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "online")

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        return bool(self.state_data.get("online"))
