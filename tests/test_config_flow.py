"""Local confirmation must work without making cloud requests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.glowrium import config_flow as module
from custom_components.glowrium.bluetooth.transport import BleUnavailable


@pytest.fixture
def flow(hass, monkeypatch):
    monkeypatch.setattr(module, "DEFAULT_API_URL", "https://api.example.test")
    instance = module.GlowriumConfigFlow()
    instance.hass = hass
    instance.context = {"source": "user"}
    instance.async_set_unique_id = AsyncMock()
    instance._abort_if_unique_id_configured = MagicMock()
    return instance


async def test_user_can_choose_cloud_or_local(flow):
    result = await flow.async_step_user()
    assert result["type"] == "menu"
    assert result["menu_options"] == ["cloud", "local"]


async def test_cloud_setup_is_hidden_without_api_url(flow, monkeypatch):
    monkeypatch.setattr(module, "DEFAULT_API_URL", "")
    result = await flow.async_step_user()
    assert result["menu_options"] == ["local"]
    assert (await flow.async_step_cloud())["reason"] == "cloud_unavailable"


async def test_cloud_form_only_requests_credentials(flow):
    result = await flow.async_step_cloud()
    assert result["type"] == "form"
    assert {key.schema for key in result["data_schema"].schema} == {
        "email",
        "password",
    }


async def test_cloud_login_uses_built_in_api_and_brand(flow):
    api = MagicMock(devices=AsyncMock(return_value=[]))
    flow._login = AsyncMock(
        return_value=(api, {
            "userId": "account-1", "token": "test-token",
            "refreshToken": "refresh-token", "linkId": "ha-link",
        })
    )

    result = await flow.async_step_cloud(
        {"email": "user@example.test", "password": "secret"}
    )

    assert result["type"] == "create_entry"
    assert result["data"]["api_url"] == module.DEFAULT_API_URL
    assert result["data"]["brand"] == module.DEFAULT_BRAND
    assert result["data"]["token"] == "test-token"
    assert result["data"]["refresh_token"] == "refresh-token"
    assert result["data"]["link_id"] == "ha-link"
    assert flow._login.await_args.args[0] == {
        "email": "user@example.test",
        "password": "secret",
        "api_url": module.DEFAULT_API_URL,
        "brand": module.DEFAULT_BRAND,
    }
    flow.async_set_unique_id.assert_awaited_once_with(
        f"{module.DEFAULT_API_URL}:account-1"
    )
    assert len(flow._login.await_args.args[1]) == 32


async def test_discovery_never_connects_before_confirmation(
    flow, advertisement, monkeypatch
):
    monkeypatch.setattr(module, "parse_advertisement", lambda info: advertisement)
    transport = MagicMock()
    monkeypatch.setattr(module, "BleTransport", transport)
    result = await flow.async_step_bluetooth(object())
    assert result["step_id"] == "local_confirm"
    transport.assert_not_called()
    result = await flow.async_step_local_confirm({"confirm": False})
    assert result["errors"]["base"] == "confirmation_required"
    transport.assert_not_called()


async def test_local_confirmation_stores_no_cloud_credentials(
    flow, advertisement, monkeypatch
):
    flow._local = advertisement
    transport = MagicMock(refresh=AsyncMock(), close=AsyncMock())
    monkeypatch.setattr(module, "BleTransport", lambda *args: transport)
    flow._login = AsyncMock()
    result = await flow.async_step_local_confirm({"confirm": True})
    assert result["type"] == "create_entry"
    assert result["data"]["mode"] == "bluetooth"
    assert "token" not in result["data"]
    assert "user_id" not in result["data"]
    flow._login.assert_not_awaited()
    transport.close.assert_awaited_once()


async def test_failed_local_probe_leaves_no_entry(flow, advertisement, monkeypatch):
    flow._local = advertisement
    transport = MagicMock(
        refresh=AsyncMock(side_effect=BleUnavailable()),
        close=AsyncMock(),
    )
    monkeypatch.setattr(module, "BleTransport", lambda *args: transport)
    result = await flow.async_step_local_confirm({"confirm": True})
    assert result["errors"]["base"] == "cannot_connect_bluetooth"
    transport.close.assert_awaited_once()


async def test_reauthentication_rejects_different_account(flow):
    flow._reauth_data = {"user_id": "original", "link_id": "ha-link"}
    api = MagicMock(unlink=AsyncMock())
    flow._login = AsyncMock(
        return_value=(api, {
            "userId": "different", "token": "token",
            "refreshToken": "refresh", "linkId": "ha-link",
        })
    )
    result = await flow.async_step_reauth_confirm(
        {"email": "someone@example.test", "password": "test"}
    )
    assert result["errors"]["base"] == "wrong_account"
    api.unlink.assert_awaited_once()
