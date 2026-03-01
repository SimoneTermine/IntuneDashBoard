"""
Microsoft Graph authentication via MSAL.
Supports:
  A) Delegated - Device Code Flow (interactive, for admin users)
  B) App-only  - Client Credentials with certificate (service/automation)

Token cache is persisted to disk (encrypted on Windows via DPAPI if available).
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable

import msal

from app.config import AppConfig, MSAL_CACHE_PATH, DEFAULT_SCOPES

logger = logging.getLogger(__name__)


class AuthError(Exception):
    pass


class MSALAuth:
    """MSAL authentication wrapper."""

    def __init__(self):
        self._app: Optional[msal.PublicClientApplication | msal.ConfidentialClientApplication] = None
        self._cache = msal.SerializableTokenCache()
        self._load_cache()

    # ------------------------------------------------------------------
    # Cache persistence
    # ------------------------------------------------------------------
    def _load_cache(self):
        if MSAL_CACHE_PATH.exists():
            try:
                with open(MSAL_CACHE_PATH, "r", encoding="utf-8") as f:
                    self._cache.deserialize(f.read())
                logger.debug("MSAL cache loaded from disk")
            except Exception as e:
                logger.warning(f"Could not load MSAL cache: {e}")

    def _save_cache(self):
        if self._cache.has_state_changed:
            try:
                with open(MSAL_CACHE_PATH, "w", encoding="utf-8") as f:
                    f.write(self._cache.serialize())
                logger.debug("MSAL cache saved")
            except Exception as e:
                logger.warning(f"Could not save MSAL cache: {e}")

    # ------------------------------------------------------------------
    # Build MSAL app
    # ------------------------------------------------------------------
    def _build_public_app(self) -> msal.PublicClientApplication:
        cfg = AppConfig()
        authority = f"https://login.microsoftonline.com/{cfg.tenant_id}"
        app = msal.PublicClientApplication(
            client_id=cfg.client_id,
            authority=authority,
            token_cache=self._cache,
        )
        return app

    def _build_confidential_app(self) -> msal.ConfidentialClientApplication:
        cfg = AppConfig()
        authority = f"https://login.microsoftonline.com/{cfg.tenant_id}"
        cert_path = cfg.get("cert_path", "")
        cert_thumbprint = cfg.get("cert_thumbprint", "")

        if not cert_path or not Path(cert_path).exists():
            raise AuthError("Certificate file not found. Check Settings > Tenant/Auth.")

        with open(cert_path, "rb") as f:
            private_key = f.read()

        app = msal.ConfidentialClientApplication(
            client_id=cfg.client_id,
            authority=authority,
            client_credential={"thumbprint": cert_thumbprint, "private_key": private_key},
            token_cache=self._cache,
        )
        return app

    # ------------------------------------------------------------------
    # Token acquisition
    # ------------------------------------------------------------------
    def get_token_device_code(
        self,
        scopes: List[str] | None = None,
        device_code_callback: Callable[[Dict], None] | None = None,
    ) -> str:
        """
        Acquire token via device code flow.
        device_code_callback(flow) is called with the user_code and verification_uri
        so the caller can display them to the user.
        Returns access_token string.
        """
        if scopes is None:
            scopes = DEFAULT_SCOPES

        app = self._build_public_app()

        # Try silent first
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(scopes, account=accounts[0])
            if result and "access_token" in result:
                self._save_cache()
                logger.debug("Token acquired silently")
                return result["access_token"]

        # Device code flow
        flow = app.initiate_device_flow(scopes=scopes)
        if "user_code" not in flow:
            raise AuthError(f"Failed to initiate device flow: {flow.get('error_description', flow)}")

        logger.info(f"Device code flow initiated: {flow['message']}")

        if device_code_callback:
            device_code_callback(flow)

        result = app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise AuthError(f"Authentication failed: {result.get('error_description', result)}")

        self._save_cache()
        logger.info("Authentication successful via device code")
        return result["access_token"]

    def get_token_app_only(self, scopes: List[str] | None = None) -> str:
        """Acquire token via client credentials (app-only)."""
        if scopes is None:
            scopes = ["https://graph.microsoft.com/.default"]

        app = self._build_confidential_app()
        result = app.acquire_token_for_client(scopes=scopes)

        if "access_token" not in result:
            raise AuthError(f"App-only auth failed: {result.get('error_description', result)}")

        self._save_cache()
        logger.info("Authentication successful via client credentials (app-only)")
        return result["access_token"]

    def get_token(
        self,
        scopes: List[str] | None = None,
        device_code_callback: Callable | None = None,
    ) -> str:
        """Get token based on configured auth mode."""
        cfg = AppConfig()
        if cfg.auth_mode == "app_only":
            return self.get_token_app_only(scopes)
        else:
            return self.get_token_device_code(scopes, device_code_callback)

    def clear_cache(self):
        """Clear the token cache (logout)."""
        try:
            if MSAL_CACHE_PATH.exists():
                MSAL_CACHE_PATH.unlink()
            self._cache = msal.SerializableTokenCache()
            self._app = None
            logger.info("MSAL cache cleared")
        except Exception as e:
            logger.warning(f"Error clearing cache: {e}")

    def has_cached_token(self) -> bool:
        """Check if there's a cached account/token."""
        try:
            app = self._build_public_app()
            return len(app.get_accounts()) > 0
        except Exception:
            return False


# Singleton
_auth_instance: Optional[MSALAuth] = None


def get_auth() -> MSALAuth:
    global _auth_instance
    if _auth_instance is None:
        _auth_instance = MSALAuth()
    return _auth_instance
