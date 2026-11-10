"""Shared Glowrium entity support."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GlowriumCoordinator
from .identity import normalize_mac


class GlowriumEntity(CoordinatorEntity[GlowriumCoordinator]):
    """Base entity backed by a Glowrium coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: GlowriumCoordinator, device_id: str, suffix: str
    ) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        self.device = coordinator.devices[device_id]
        self._attr_unique_id = f"{device_id}_{suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=self.device.get("name") or f"Glowrium {device_id}",
            manufacturer="Glowrium",
            model=self.device.get("productKey"),
            sw_version=self.device.get("firmwareVersion"),
        )
        if mac := normalize_mac(self.device.get("bluetoothMac")):
            self._attr_device_info["connections"] = {
                ("bluetooth", ":".join(mac[i : i + 2] for i in range(0, 12, 2)))
            }

    @property
    def state_data(self) -> dict:
        """Latest normalized state for this device."""
        return self.coordinator.data.get(self.device_id, {})

    @property
    def available(self) -> bool:
        return super().available and bool(self.state_data.get("online"))

    async def async_command(self, command: str, **values) -> None:
        await self.coordinator.async_command(self.device_id, command, **values)
