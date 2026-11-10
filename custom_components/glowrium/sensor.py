"""Sensor entities for Glowrium."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory

from . import GlowriumConfigEntry
from .entity import GlowriumEntity


async def async_setup_entry(
    hass, entry: GlowriumConfigEntry, async_add_entities
) -> None:
    coordinator = entry.runtime_data
    coordinator.async_register_entities(
        entry,
        async_add_entities,
        lambda hub, device_id: [GlowriumFirmwareSensor(hub, device_id)],
    )


class GlowriumFirmwareSensor(GlowriumEntity, SensorEntity):
    """Firmware version from the cloud catalog or BLE advertisement."""

    _attr_name = "Firmware"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "firmware")

    @property
    def native_value(self) -> str | None:
        return self.device.get("firmwareVersion")
