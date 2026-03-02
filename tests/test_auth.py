from unittest.mock import Mock

import pytest

import app.config as cfg


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    cfg.APP_DIR = tmp_path
    cfg.MSAL_CACHE_PATH = tmp_path / "msal_cache.bin"
    cfg.LEGACY_MSAL_CACHE_PATH = tmp_path / "legacy_msal_cache.bin"
    cfg.CONFIG_PATH = tmp_path / "config.json"
    cfg.DEFAULT_CONFIG["client_id"] = "test-client-id"
    cfg.DEFAULT_CONFIG["tenant_id"] = "test-tenant-id"


from app.config import DEFAULT_SCOPES
from app.graph.auth import MSALAuth


def test_default_scopes_include_device_management_configuration_read_all():
    assert "https://graph.microsoft.com/DeviceManagementConfiguration.Read.All" in DEFAULT_SCOPES


def test_get_token_device_code_prefers_silent(monkeypatch):
    auth = MSALAuth()

    fake_app = Mock()
    fake_app.get_accounts.return_value = [{"home_account_id": "abc"}]
    fake_app.acquire_token_silent.return_value = {
        "access_token": "silent-token",
        "scope": " ".join([s.split("/")[-1] for s in DEFAULT_SCOPES]),
    }

    monkeypatch.setattr(auth, "_build_public_app", lambda: fake_app)

    token = auth.get_token_device_code()

    assert token == "silent-token"
    fake_app.initiate_device_flow.assert_not_called()


def test_get_token_device_code_falls_back_to_device_code_when_consent_needed(monkeypatch):
    auth = MSALAuth()

    fake_app = Mock()
    fake_app.get_accounts.return_value = [{"home_account_id": "abc"}]
    fake_app.acquire_token_silent.return_value = {"error": "consent_required"}
    fake_app.initiate_device_flow.return_value = {
        "user_code": "ABCD-1234",
        "verification_uri": "https://microsoft.com/devicelogin",
        "message": "Sign in",
    }
    fake_app.acquire_token_by_device_flow.return_value = {
        "access_token": "interactive-token",
        "scope": " ".join([s.split("/")[-1] for s in DEFAULT_SCOPES]),
    }

    monkeypatch.setattr(auth, "_build_public_app", lambda: fake_app)

    token = auth.get_token_device_code()

    assert token == "interactive-token"
    fake_app.initiate_device_flow.assert_called_once()


def test_admin_consent_url_defaults_without_redirect_uri():
    url = MSALAuth.build_admin_consent_url()
    assert "adminconsent?client_id=" in url
    assert "redirect_uri=" not in url


def test_admin_consent_url_can_include_redirect_uri():
    url = MSALAuth.build_admin_consent_url(include_redirect_uri=True)
    assert "redirect_uri=" in url


def test_get_token_device_code_surfaces_aadsts1003031(monkeypatch):
    auth = MSALAuth()

    fake_app = Mock()
    fake_app.get_accounts.return_value = []
    fake_app.initiate_device_flow.return_value = {
        "user_code": "ABCD-1234",
        "verification_uri": "https://microsoft.com/devicelogin",
        "message": "Sign in",
    }
    fake_app.acquire_token_by_device_flow.return_value = {
        "error": "invalid_client",
        "error_description": "AADSTS1003031: Misconfigured required resource access in client application registration.",
    }

    monkeypatch.setattr(auth, "_build_public_app", lambda: fake_app)

    with pytest.raises(Exception) as exc:
        auth.get_token_device_code()

    assert "AADSTS1003031" in str(exc.value)
