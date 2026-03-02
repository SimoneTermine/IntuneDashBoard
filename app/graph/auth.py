"""
Microsoft Graph authentication via MSAL.

Features:
  - Device Code Flow (delegated)
  - Client Credentials (app-only)
  - Silent-first token acquisition
  - Persistent cache with DPAPI encryption on Windows when msal-extensions is available
  - Incremental consent support for newly added scopes
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional, List, Dict, Callable

import msal

from app.config import (
    AppConfig,
    DEFAULT_SCOPES,
    LEGACY_MSAL_CACHE_PATH,
    MSAL_CACHE_PATH,
)

logger = logging.getLogger(__name__)


class AuthError(Exception):
    pass


class AdminConsentRequiredError(AuthError):
    def __init__(self, message: str, admin_consent_url: str):
        super().__init__(message)
        self.admin_consent_url = admin_consent_url


class MSALAuth:
    """MSAL authentication wrapper."""

    def __init__(self):
        self._app: Optional[msal.PublicClientApplication | msal.ConfidentialClientApplication] = None
        self._cache = None
        self._cache_path = MSAL_CACHE_PATH
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_cache_if_needed()
        self._init_token_cache()

    # ------------------------------------------------------------------
    # Cache persistence
    # ------------------------------------------------------------------
    def _migrate_legacy_cache_if_needed(self):
        """Move old local-appdata cache to roaming path when needed."""
        if self._cache_path.exists() or not LEGACY_MSAL_CACHE_PATH.exists():
            return

        try:
            self._cache_path.write_bytes(LEGACY_MSAL_CACHE_PATH.read_bytes())
            LEGACY_MSAL_CACHE_PATH.unlink()
            logger.info("Migrated MSAL cache from legacy LOCALAPPDATA path to APPDATA")
        except Exception as e:
            logger.warning(f"Could not migrate legacy MSAL cache: {e}")

    def _init_token_cache(self):
        """Initialize persistent cache, preferring DPAPI encryption on Windows."""
        try:
            from msal_extensions import FilePersistenceWithDataProtection, PersistedTokenCache

            persistence = FilePersistenceWithDataProtection(str(self._cache_path))
            self._cache = PersistedTokenCache(persistence)
            logger.info("Using encrypted DPAPI token cache")
            return
        except Exception as e:
            logger.debug(f"DPAPI cache unavailable, using SerializableTokenCache fallback: {e}")

        self._cache = msal.SerializableTokenCache()
        if self._cache_path.exists():
            try:
                self._cache.deserialize(self._cache_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Could not load MSAL cache: {e}")

    def _save_cache(self):
        # PersistedTokenCache auto-saves via msal-extensions.
        if hasattr(self._cache, "has_state_changed") and self._cache.has_state_changed:
            try:
                self._cache_path.write_text(self._cache.serialize(), encoding="utf-8")
                if os.name == "nt":
                    try:
                        os.chmod(self._cache_path, 0o600)
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"Could not save MSAL cache: {e}")

    # ------------------------------------------------------------------
    # Build MSAL app
    # ------------------------------------------------------------------
    def _build_public_app(self) -> msal.PublicClientApplication:
        cfg = AppConfig()
        authority = f"https://login.microsoftonline.com/{cfg.tenant_id or 'common'}"
        return msal.PublicClientApplication(
            client_id=cfg.client_id,
            authority=authority,
            token_cache=self._cache,
        )

    def _build_confidential_app(self) -> msal.ConfidentialClientApplication:
        cfg = AppConfig()
        authority = f"https://login.microsoftonline.com/{cfg.tenant_id or 'common'}"
        cert_path = cfg.get("cert_path", "")
        cert_thumbprint = cfg.get("cert_thumbprint", "")

        if not cert_path or not Path(cert_path).exists():
            raise AuthError("Certificate file not found. Check Settings > Tenant/Auth.")

        with open(cert_path, "rb") as f:
            private_key = f.read()

        return msal.ConfidentialClientApplication(
            client_id=cfg.client_id,
            authority=authority,
            client_credential={"thumbprint": cert_thumbprint, "private_key": private_key},
            token_cache=self._cache,
        )

    # ------------------------------------------------------------------
    # Consent helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _missing_required_scopes(token_result: dict, requested_scopes: list) -> list[str]:
        """
        Return missing scope names when MSAL response exposes granted scopes.

        If the result does not contain a `scope` field, return empty list and trust
        the token (Graph/API call will enforce effective permissions).
        """
        scope_value = token_result.get("scope")
        if not scope_value:
            return []

        granted = set(scope_value.lower().split())
        missing: list[str] = []
        for scope in requested_scopes:
            name = scope.split("/")[-1].lower()
            if name not in granted:
                missing.append(scope.split("/")[-1])
        return missing

    @staticmethod
    def build_admin_consent_url(include_redirect_uri: bool = False) -> str:
        """
        Build admin consent URL.

        NOTE: many tenants/app registrations return AADSTS500113 when adminconsent is
        called with redirect_uri but no reply address is configured for the app.
        We therefore default to omitting redirect_uri, and only include it on demand.
        """
        cfg = AppConfig()
        tenant = cfg.tenant_id or "common"
        base = f"https://login.microsoftonline.com/{tenant}/adminconsent?client_id={cfg.client_id}"
        if include_redirect_uri:
            return (
                base
                + "&redirect_uri=https%3A%2F%2Flogin.microsoftonline.com%2Fcommon%2Foauth2%2Fnativeclient"
            )
        return base

    def _raise_admin_consent_required(self, missing_scopes: list[str] | None = None):
        suffix = ""
        if missing_scopes:
            suffix = f" Missing delegated scope(s): {', '.join(missing_scopes)}."
        raise AdminConsentRequiredError(
            "Admin consent required for one or more Microsoft Graph permissions."
            + suffix
            + " Ask a tenant admin to grant consent.",
            self.build_admin_consent_url(include_redirect_uri=False),
        )

    # ------------------------------------------------------------------
    # Token acquisition
    # ------------------------------------------------------------------
    def get_token_device_code(
        self,
        scopes: List[str] | None = None,
        device_code_callback: Callable[[Dict], None] | None = None,
    ) -> str:
        """Acquire token with silent-first strategy and fallback to device code."""
        scopes = scopes or DEFAULT_SCOPES
        app = self._build_public_app()

        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(scopes, account=accounts[0])
            if result and "access_token" in result:
                missing = self._missing_required_scopes(result, scopes)
                if not missing:
                    self._save_cache()
                    logger.debug("Token acquired silently")
                    return result["access_token"]
                logger.info(
                    "Cached token appears to miss required scope(s): %s. Falling back to device code.",
                    ", ".join(missing),
                )

            if result and result.get("error") in {"consent_required", "interaction_required", "invalid_grant"}:
                logger.info("Silent auth requires interaction/consent, falling back to device code")

        flow = app.initiate_device_flow(scopes=scopes)
        if "user_code" not in flow:
            raise AuthError(f"Failed to initiate device flow: {flow.get('error_description', flow)}")

        if device_code_callback:
            device_code_callback(flow)

        result = app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            error_text = (result.get("error") or "") + " " + (result.get("error_description") or "")
            lowered = error_text.lower()
            if "aadsts65001" in lowered or "consent_required" in lowered or "insufficient" in lowered:
                self._raise_admin_consent_required()
            if "aadsts1003031" in lowered:
                raise AuthError(
                    "AADSTS1003031: Misconfigured required resource access in client application registration. "
                    "Open Entra App Registration and fix API permissions/manifest, then grant admin consent."
                )
            raise AuthError(f"Authentication failed: {result.get('error_description', result)}")

        missing = self._missing_required_scopes(result, scopes)
        if missing:
            self._raise_admin_consent_required(missing)

        self._save_cache()
        return result["access_token"]

    def get_token_app_only(self, scopes: List[str] | None = None) -> str:
        scopes = scopes or ["https://graph.microsoft.com/.default"]

        app = self._build_confidential_app()
        result = app.acquire_token_for_client(scopes=scopes)

        if "access_token" not in result:
            raise AuthError(f"App-only auth failed: {result.get('error_description', result)}")

        self._save_cache()
        return result["access_token"]

    def get_token(
        self,
        scopes: List[str] | None = None,
        device_code_callback: Callable | None = None,
    ) -> str:
        cfg = AppConfig()
        if cfg.auth_mode == "app_only":
            return self.get_token_app_only(scopes)
        return self.get_token_device_code(scopes, device_code_callback)

    def clear_cache(self):
        """Full logout: remove accounts and delete local cache files."""
        try:
            app = self._build_public_app()
            for account in app.get_accounts() or []:
                try:
                    app.remove_account(account)
                except Exception as e:
                    logger.debug(f"Could not remove account from cache: {e}")
        except Exception:
            pass

        for path in [self._cache_path, Path(str(self._cache_path) + ".lockfile"), LEGACY_MSAL_CACHE_PATH]:
            try:
                if path.exists():
                    path.unlink()
            except Exception as e:
                logger.warning(f"Could not remove cache file {path}: {e}")

        self._app = None
        self._init_token_cache()

    def has_cached_token(self) -> bool:
        try:
            app = self._build_public_app()
            return len(app.get_accounts()) > 0
        except Exception:
            return False


_auth_instance: Optional[MSALAuth] = None


def get_auth() -> MSALAuth:
    global _auth_instance
    if _auth_instance is None:
        _auth_instance = MSALAuth()
    return _auth_instance
