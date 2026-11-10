"""HTTP client for the Glowrium cloud API."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

from aiohttp import ClientError, ClientSession, ClientTimeout


class GlowriumApiError(Exception):
    """Base Glowrium API error."""


class GlowriumAuthError(GlowriumApiError):
    """Authentication failed or expired."""


class GlowriumAccountMismatchError(GlowriumAuthError):
    """This HA link belongs to another Glowrium account."""


class GlowriumApi:
    """Small async client for the Home Assistant adapter endpoints."""

    def __init__(
        self,
        session: ClientSession,
        base_url: str,
        token: str | None = None,
        *,
        refresh_token: str | None = None,
        link_id: str | None = None,
        on_tokens: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._refresh_token = refresh_token
        self._link_id = link_id
        self._on_tokens = on_tokens
        self._refresh_lock = asyncio.Lock()

    @property
    def token(self) -> str | None:
        return self._token

    async def login(
        self, brand: str, email: str, password: str, link_id: str
    ) -> dict[str, Any]:
        response = await self._request(
            "POST",
            "/api/homeassistant/v1/links/login",
            json={
                "brand": brand,
                "email": email,
                "password": password,
                "linkId": link_id,
            },
            authenticated=False,
        )
        if (
            not isinstance(response, dict)
            or not response.get("accessToken")
            or not response.get("refreshToken")
        ):
            raise GlowriumAuthError("Home Assistant credentials missing")
        self._token = response["accessToken"]
        self._refresh_token = response["refreshToken"]
        self._link_id = link_id
        return {
            "token": self._token,
            "refreshToken": self._refresh_token,
            "linkId": link_id,
            "userId": response["userId"],
        }

    async def validate(self) -> dict[str, Any]:
        return await self._request("GET", "/api/homeassistant/v1/me")

    async def devices(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/api/homeassistant/v1/devices")

    async def unlink(self) -> None:
        await self._request(
            "DELETE", f"/api/homeassistant/v1/links/{quote(self._link_id)}"
        )

    async def state(self, device_id: str) -> dict[str, Any]:
        return await self._request(
            "GET", f"/api/homeassistant/v1/devices/{device_id}/state"
        )

    async def command(
        self, device_id: str, command: str, **values: Any
    ) -> dict[str, Any]:
        payload = {"command": command, **values}
        return await self._request(
            "POST", f"/api/homeassistant/v1/devices/{device_id}/commands", json=payload
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        allow_refresh: bool = True,
        **kwargs: Any,
    ) -> Any:
        headers = dict(kwargs.pop("headers", {}))
        kwargs.setdefault("timeout", ClientTimeout(total=20))
        token_used = self._token
        if authenticated and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            async with self._session.request(
                method, f"{self._base_url}{path}", headers=headers, **kwargs
            ) as response:
                if response.status == 401:
                    if (
                        authenticated
                        and allow_refresh
                        and self._refresh_token
                        and self._link_id
                    ):
                        await self._refresh_credentials(token_used)
                        return await self._request(
                            method, path, authenticated=authenticated,
                            allow_refresh=False, **kwargs
                        )
                    raise GlowriumAuthError("Authentication expired")
                if response.status == 403:
                    raise GlowriumAuthError("Home Assistant access denied")
                if response.status == 409:
                    raise GlowriumAccountMismatchError("Wrong Glowrium account")
                response.raise_for_status()
                if response.status == 204:
                    return None
                return await response.json()
        except GlowriumAuthError:
            raise
        except (ClientError, TimeoutError, OSError, ValueError) as err:
            raise GlowriumApiError(str(err)) from err

    async def _refresh_credentials(self, rejected_token: str | None) -> None:
        async with self._refresh_lock:
            if self._token != rejected_token:
                return
            credentials = await self._request(
                "POST",
                "/api/homeassistant/v1/links/refresh",
                authenticated=False,
                json={"linkId": self._link_id, "refreshToken": self._refresh_token},
            )
            if (
                not isinstance(credentials, dict)
                or not credentials.get("accessToken")
                or not credentials.get("refreshToken")
            ):
                raise GlowriumApiError("Home Assistant refresh response is incomplete")
            self._token = credentials["accessToken"]
            self._refresh_token = credentials["refreshToken"]
            if self._on_tokens is not None:
                await self._on_tokens(self._token, self._refresh_token)
