"""Glowrium cloud and independently configured local Bluetooth devices."""

from __future__ import annotations

import asyncio
import logging
from typing import TypeAlias

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GlowriumApi, GlowriumApiError, GlowriumAuthError
from .const import (
    CONF_LINK_ID,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN,
    CONF_USER_ID,
    DEFAULT_API_URL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import GlowriumCoordinator

_LOGGER = logging.getLogger(__name__)

GlowriumConfigEntry: TypeAlias = ConfigEntry[GlowriumCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: GlowriumConfigEntry) -> bool:
    """Cloud tokens never gate setup of a standalone local entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data.setdefault("lock", asyncio.Lock())
    domain_data.setdefault("credential_updates", {})
    async with domain_data["lock"]:
        if "hub" not in domain_data:
            coordinator = GlowriumCoordinator(hass)
            await coordinator.async_load()
            domain_data["hub"] = coordinator

            async def on_stop(event):
                await coordinator.async_close()

            domain_data["stop_listener"] = hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STOP, on_stop
            )
        coordinator = domain_data["hub"]
        if entry.data.get("mode") == "bluetooth":
            await coordinator.async_add_local(entry)
        else:
            if DEFAULT_API_URL and entry.data.get("api_url") != DEFAULT_API_URL:
                new_data = {**entry.data, "api_url": DEFAULT_API_URL}
                domain_data["credential_updates"][entry.entry_id] = new_data
                update = {"data": new_data}
                if user_id := entry.data.get(CONF_USER_ID):
                    update["unique_id"] = f"{DEFAULT_API_URL}:{user_id}"
                hass.config_entries.async_update_entry(entry, **update)
            if not entry.data.get(CONF_LINK_ID) or not entry.data.get(
                CONF_REFRESH_TOKEN
            ):
                raise ConfigEntryAuthFailed("Home Assistant credentials need renewal")

            async def save_tokens(token: str, refresh_token: str) -> None:
                new_data = {
                    **entry.data,
                    CONF_TOKEN: token,
                    CONF_REFRESH_TOKEN: refresh_token,
                }
                domain_data["credential_updates"][entry.entry_id] = new_data
                hass.config_entries.async_update_entry(
                    entry,
                    data=new_data,
                )

            api = GlowriumApi(
                async_get_clientsession(hass),
                DEFAULT_API_URL or entry.data["api_url"],
                entry.data[CONF_TOKEN],
                refresh_token=entry.data[CONF_REFRESH_TOKEN],
                link_id=entry.data[CONF_LINK_ID],
                on_tokens=save_tokens,
            )
            try:
                await api.validate()
                devices = await api.devices()
            except GlowriumAuthError as err:
                raise ConfigEntryAuthFailed from err
            except GlowriumApiError as err:
                raise ConfigEntryNotReady(str(err)) from err
            await coordinator.async_add_account(entry, api, devices)
        entry.runtime_data = coordinator
        try:
            await coordinator.async_refresh()
            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        except Exception:
            await coordinator.async_remove_entry(entry.entry_id)
            raise
        if "voice_unsub" not in domain_data:
            try:
                from .voice import register_voice_commands

                domain_data["voice_unsub"] = register_voice_commands(hass, coordinator)
            except Exception:
                _LOGGER.exception("Unable to register Glowrium Assist commands")
        domain_data["credential_updates"].pop(entry.entry_id, None)
        entry.async_on_unload(entry.add_update_listener(_async_reload))
        entry.async_on_unload(coordinator.async_add_listener(lambda: None))
    return True


async def _async_reload(hass: HomeAssistant, entry: GlowriumConfigEntry) -> None:
    updates = hass.data.get(DOMAIN, {}).get("credential_updates", {})
    if updates.pop(entry.entry_id, None) == entry.data:
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: GlowriumConfigEntry) -> bool:
    """Keep the other transport alive when its own entry still exists."""
    domain_data = hass.data[DOMAIN]
    async with domain_data["lock"]:
        if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
            return False
        coordinator = entry.runtime_data
        await coordinator.async_remove_entry(entry.entry_id)
        if not coordinator.accounts and not coordinator.local_entries:
            if voice_unsub := domain_data.pop("voice_unsub", None):
                voice_unsub()
            await coordinator.async_close()
            domain_data.pop("hub", None)
            domain_data.pop("stop_listener")()
    return True


async def async_remove_entry(hass: HomeAssistant, entry: GlowriumConfigEntry) -> None:
    """Remove the server link only when HA deletes the cloud config entry."""
    if entry.data.get("mode") != "cloud":
        return
    link_id = entry.data.get(CONF_LINK_ID)
    if not link_id:
        return
    api = GlowriumApi(
        async_get_clientsession(hass),
        DEFAULT_API_URL or entry.data["api_url"],
        entry.data[CONF_TOKEN],
        refresh_token=entry.data.get(CONF_REFRESH_TOKEN), link_id=link_id,
    )
    try:
        await api.unlink()
    except (GlowriumAuthError, GlowriumApiError):
        _LOGGER.warning(
            "Could not remove the Glowrium cloud account link", exc_info=True
        )
