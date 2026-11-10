"""Choose account-based cloud access or local Bluetooth without an account."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    GlowriumAccountMismatchError,
    GlowriumApi,
    GlowriumApiError,
    GlowriumAuthError,
)
from .bluetooth.advertisement import GlowriumAdvertisement, parse_advertisement
from .bluetooth.transport import BleTransport, BleUnavailable
from .const import (
    CONF_BRAND,
    CONF_LINK_ID,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN,
    CONF_USER_ID,
    DEFAULT_API_URL,
    DEFAULT_BRAND,
    DOMAIN,
)

CONF_API_URL = "api_url"


class GlowriumConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """One cloud entry per account and one local entry per physical device."""

    VERSION = 1
    _local: GlowriumAdvertisement | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        menu_options = ["cloud", "local"] if DEFAULT_API_URL else ["local"]
        return self.async_show_menu(step_id="user", menu_options=menu_options)

    async def async_step_cloud(self, user_input: dict[str, Any] | None = None):
        if not DEFAULT_API_URL:
            return self.async_abort(reason="cloud_unavailable")
        errors: dict[str, str] = {}
        if user_input is not None:
            api = None
            try:
                api, data = await self._login(
                    {
                        **user_input,
                        CONF_API_URL: DEFAULT_API_URL,
                        CONF_BRAND: DEFAULT_BRAND,
                    },
                    uuid4().hex,
                )
                await api.devices()
            except GlowriumAccountMismatchError:
                errors["base"] = "wrong_account"
            except GlowriumAuthError:
                if api is not None:
                    await self._discard_link(api)
                errors["base"] = "invalid_auth"
            except GlowriumApiError:
                if api is not None:
                    await self._discard_link(api)
                errors["base"] = "cannot_connect"
            else:
                user_id = data["userId"]
                await self.async_set_unique_id(f"{DEFAULT_API_URL}:{user_id}")
                try:
                    self._abort_if_unique_id_configured()
                except Exception:
                    await self._discard_link(api)
                    raise
                return self.async_create_entry(
                    title=user_input[CONF_EMAIL],
                    data={
                        "mode": "cloud",
                        CONF_API_URL: DEFAULT_API_URL,
                        CONF_BRAND: DEFAULT_BRAND,
                        CONF_TOKEN: data["token"],
                        CONF_REFRESH_TOKEN: data["refreshToken"],
                        CONF_LINK_ID: data["linkId"],
                        CONF_USER_ID: user_id,
                    },
                )
        return self.async_show_form(
            step_id="cloud", data_schema=self._schema(user_input), errors=errors
        )

    async def async_step_local(self, user_input: dict[str, Any] | None = None):
        found = {}
        for info in bluetooth.async_discovered_service_info(
            self.hass, connectable=True
        ):
            adv = parse_advertisement(info)
            if adv:
                found[adv.key] = adv
        if not found:
            return self.async_abort(reason="no_devices_found")
        if user_input is not None and user_input.get("device") in found:
            self._local = found[user_input["device"]]
            return await self._local_confirm()
        return self.async_show_form(
            step_id="local",
            data_schema=vol.Schema(
                {
                    vol.Required("device"): vol.In(
                        {
                            key: f"{adv.name} ({adv.product_key}, {adv.mac[-6:]})"
                            for key, adv in found.items()
                        }
                    )
                }
            ),
        )

    async def async_step_bluetooth(
        self, discovery_info: bluetooth.BluetoothServiceInfoBleak
    ):
        """Discovery only prompts; it never connects to an unconfirmed light."""
        self._local = parse_advertisement(discovery_info)
        if self._local is None:
            return self.async_abort(reason="unsupported_device")
        return await self._local_confirm()

    async def _local_confirm(self):
        await self.async_set_unique_id(f"ble:{self._local.key}")
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"name": self._local.name}
        return await self.async_step_local_confirm()

    async def async_step_local_confirm(self, user_input: dict[str, Any] | None = None):
        errors = {}
        if user_input is not None:
            if not user_input.get("confirm"):
                errors["base"] = "confirmation_required"
            else:
                # Read attributes only: no activation, clock, reset or ownership writes.
                transport = BleTransport(self.hass, self._local, lambda state: None)
                try:
                    await transport.refresh(force=True)
                except BleUnavailable:
                    errors["base"] = "cannot_connect_bluetooth"
                else:
                    return self.async_create_entry(
                        title=self._local.name,
                        data={"mode": "bluetooth", "device": self._local.as_dict()},
                    )
                finally:
                    await transport.close()
        return self.async_show_form(
            step_id="local_confirm",
            data_schema=vol.Schema({vol.Required("confirm", default=False): bool}),
            description_placeholders={
                "name": self._local.name,
                "model": self._local.product_key,
                "mac": self._local.mac,
            },
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]):
        self._reauth_data = entry_data
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                link_id = (
                    self._reauth_data.get(CONF_LINK_ID)
                    or self._get_reauth_entry().entry_id
                )
                api, data = await self._login(
                    {**self._reauth_data, **user_input}, link_id
                )
            except GlowriumAccountMismatchError:
                errors["base"] = "wrong_account"
            except GlowriumAuthError:
                errors["base"] = "invalid_auth"
            except GlowriumApiError:
                errors["base"] = "cannot_connect"
            else:
                if str(data["userId"]) != str(self._reauth_data[CONF_USER_ID]):
                    await self._discard_link(api)
                    errors["base"] = "wrong_account"
                else:
                    return self.async_update_reload_and_abort(
                        self._get_reauth_entry(),
                        data_updates={
                            CONF_API_URL: DEFAULT_API_URL
                            or self._reauth_data[CONF_API_URL],
                            CONF_TOKEN: data["token"],
                            CONF_REFRESH_TOKEN: data["refreshToken"],
                            CONF_LINK_ID: data["linkId"],
                            CONF_USER_ID: data["userId"],
                        },
                    )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def _login(self, values: dict[str, Any], link_id: str):
        api = GlowriumApi(
            async_get_clientsession(self.hass),
            DEFAULT_API_URL or values[CONF_API_URL],
        )
        data = await api.login(
            values[CONF_BRAND], values[CONF_EMAIL], values[CONF_PASSWORD], link_id
        )
        user_id = data.get("userId") or data.get("user_id")
        if not user_id:
            raise GlowriumAuthError("Account identifier missing")
        return api, {**data, "userId": user_id}

    @staticmethod
    async def _discard_link(api: GlowriumApi) -> None:
        try:
            await api.unlink()
        except GlowriumApiError:
            pass

    @staticmethod
    def _schema(defaults: dict[str, Any] | None) -> vol.Schema:
        defaults = defaults or {}
        return vol.Schema(
            {
                vol.Required(CONF_EMAIL, default=defaults.get(CONF_EMAIL, "")): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
