"""Real HTTP error translation used by hybrid fallback and reauthentication."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import ClientConnectionError

from custom_components.glowrium.api import (
    GlowriumApi,
    GlowriumApiError,
    GlowriumAuthError,
)


async def test_connection_error_is_translated_to_cloud_api_error():
    session = MagicMock()
    session.request.side_effect = ClientConnectionError("connection lost")
    api = GlowriumApi(session, "https://api.example.test", "secret")
    with pytest.raises(GlowriumApiError):
        await api.devices()


async def test_expired_token_starts_auth_error():
    session = MagicMock()
    response = MagicMock(status=401)
    session.request.return_value.__aenter__ = AsyncMock(return_value=response)
    api = GlowriumApi(session, "https://api.example.test", "secret")
    with pytest.raises(GlowriumAuthError):
        await api.devices()


async def test_cloud_command_retains_authenticated_payload_and_timeout():
    session = MagicMock()
    response = MagicMock(status=200, json=AsyncMock(return_value={"online": True}))
    session.request.return_value.__aenter__ = AsyncMock(return_value=response)
    api = GlowriumApi(session, "https://api.example.test", "secret")
    await api.command("owned-device", "set_brightness", brightness=80)
    call = session.request.call_args
    assert call.args == (
        "POST",
        "https://api.example.test/api/homeassistant/v1/devices/owned-device/commands",
    )
    assert call.kwargs["headers"] == {"Authorization": "Bearer secret"}
    assert call.kwargs["json"] == {"command": "set_brightness", "brightness": 80}
    assert call.kwargs["timeout"].total == 20


async def test_account_link_accepts_empty_success_response():
    session = MagicMock()
    response = MagicMock(status=204, json=AsyncMock())
    session.request.return_value.__aenter__ = AsyncMock(return_value=response)
    api = GlowriumApi(
        session, "https://api.example.test", "secret", link_id="ha-entry"
    )

    await api.unlink()

    calls = session.request.call_args_list
    assert [call.args[:2] for call in calls] == [
        ("DELETE", "https://api.example.test/api/homeassistant/v1/links/ha-entry"),
    ]
    assert all(
        call.kwargs["headers"] == {"Authorization": "Bearer secret"}
        for call in calls
    )
    response.json.assert_not_awaited()


async def test_login_requests_ha_specific_credentials():
    session = MagicMock()
    response = MagicMock(
        status=200,
        json=AsyncMock(
            return_value={
                "accessToken": "ha-access",
                "refreshToken": "ha-refresh",
                "userId": "account-1",
            }
        ),
    )
    session.request.return_value.__aenter__ = AsyncMock(return_value=response)
    api = GlowriumApi(session, "https://api.example.test")

    credentials = await api.login("Glowrium", "user@example.test", "secret", "ha-entry")

    assert credentials["token"] == "ha-access"
    assert credentials["refreshToken"] == "ha-refresh"
    call = session.request.call_args
    assert call.args == (
        "POST", "https://api.example.test/api/homeassistant/v1/links/login"
    )
    assert call.kwargs["json"] == {
        "brand": "Glowrium",
        "email": "user@example.test",
        "password": "secret",
        "linkId": "ha-entry",
    }


async def test_expired_ha_access_token_refreshes_and_retries():
    session = MagicMock()
    responses = [
        MagicMock(status=401),
        MagicMock(
            status=200,
            json=AsyncMock(
                return_value={
                    "accessToken": "new-access",
                    "refreshToken": "new-refresh",
                }
            ),
        ),
        MagicMock(status=200, json=AsyncMock(return_value={"id": "account-1"})),
    ]
    session.request.side_effect = [
        MagicMock(__aenter__=AsyncMock(return_value=response))
        for response in responses
    ]
    saved = AsyncMock()
    api = GlowriumApi(
        session, "https://api.example.test", "old-access",
        refresh_token="old-refresh", link_id="ha-entry", on_tokens=saved,
    )

    assert await api.validate() == {"id": "account-1"}
    assert [call.args[0] for call in session.request.call_args_list] == [
        "GET", "POST", "GET"
    ]
    assert session.request.call_args_list[1].kwargs["json"] == {
        "linkId": "ha-entry", "refreshToken": "old-refresh"
    }
    assert session.request.call_args_list[2].kwargs["headers"] == {
        "Authorization": "Bearer new-access"
    }
    saved.assert_awaited_once_with("new-access", "new-refresh")
