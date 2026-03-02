"""
Microsoft Graph authentication via MSAL.
Supports:
  A) Delegated - Device Code Flow (interactive, for admin users)
  B) App-only  - Client Credentials with certificate (service/automation)

Token cache is persisted to disk.

Scope change detection (v1.1.0):
  When DEFAULT_SCOPES changes between versions (e.g. a new permission is added),
  the app must re-authenticate to obtain a token that includes the new scope.
  On startup, _check_scope_change() hashes the current DEFAULT_SCOPES and compares
  it with the hash stored in msal_scopes.json next to the token cache.
  If the hash differs, the token cache is cleared automatically and the user will
  be prompted to authenticate again on the next sync or Test Connection.
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Callable

import msal

from app.config import AppConfig, MSAL_CACHE_PATH, DEFAULT_SCOPES

logger = logging.getLogger(__name__)

# Stores the hash of the scopes used during the last successful authentication
_SCOPES_HASH_PATH = MSAL_CACHE_PATH.parent / "msal_scopes.json"


class AuthError(Exception):
    pass


def _scopes_hash(scopes: list) -> str:
    """Stable hash of a sorted list of scope strings."""
    key = "|".join(sorted(scopes))
    return hashlib.sha256(key.encode()).hexdigest()[:16]


class MSALAuth:
    """MSAL authentication wrapper."""

    def __init__(self):
        self._app: Optional[msal.PublicClientApplication | msal.ConfidentialClientApplication] = None
        self._cache = msal.SerializableTokenCache()
        self._load_cache()
        self._check_scope_change()

    # ------------------------------------------------------------------
    # Scope change detection
    # ------------------------------------------------------------------
    def _check_scope_change(self):
        """
        If DEFAULT_SCOPES has changed since the last successful auth,
        clear the token cache so the user is prompted for a new login
        that includes the updated permissions.
        """
        current_hash = _scopes_hash(DEFAULT_SCOPES)
        stored_hash = None

        try:
            if _SCOPES_HASH_PATH.exists():
                data = json.loads(_SCOPES_HASH_PATH.read_text(encoding="utf-8"))
                stored_hash = data.get("hash")
        except Exception as e:
            logger.debug(f"Could not read scopes hash file: {e}")

        if stored_hash is not None and stored_hash != current_hash:
            logger.warning(
                "Required Graph API permissions have changed since last login. "
                "Clearing token cache — you will be prompted to re-authenticate "
                "with the updated permissions on next sync."
            )
            self._invalidate_cache()
        elif stored_hash is None and MSAL_CACHE_PATH.exists():
            # First run after adding scope tracking.
            # Cannot know if the cached token has the current scopes — clear it
            # to guarantee a fresh consent on next sync/auth.
            logger.info(
                "Scope tracking introduced — clearing token cache to ensure "
                "all required permissions are granted on next authentication."
            )
            self._invalidate_cache()
        self._save_scopes_hash()

    def _save_scopes_hash(self):
        """Persist the current DEFAULT_SCOPES hash after successful auth."""
        try:
            _SCOPES_HASH_PATH.write_text(
                json.dumps({"hash": _scopes_hash(DEFAULT_SCOPES), "scopes": DEFAULT_SCOPES}),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug(f"Could not save scopes hash: {e}")

    def _invalidate_cache(self):
        """Clear the MSAL token cache (without resetting the auth object)."""
        try:
            if MSAL_CACHE_PATH.exists():
                MSAL_CACHE_PATH.unlink()
            self._cache = msal.SerializableTokenCache()
            self._app = None
            logger.info("Token cache cleared due to scope change")
        except Exception as e:
            logger.warning(f"Error clearing cache: {e}")

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
        self._save_scopes_hash()

    # ------------------------------------------------------------------
    # Build MSAL app
    # ------------------------------------------------------------------
    def _build_public_app(self) -> msal.PublicClientApplication:
        cfg = AppConfig()
        authority = f"https://login.microsoftonline.com/{cfg.tenant_id}"
        return msal.PublicClientApplication(
            client_id=cfg.client_id,
            authority=authority,
            token_cache=self._cache,
        )

    def _build_confidential_app(self) -> msal.ConfidentialClientApplication:
        cfg = AppConfig()
        authority = f"https://login.microsoftonline.com/{cfg.tenant_id}"
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
    # Token acquisition
    # ------------------------------------------------------------------
    @staticmethod
    def _has_required_scopes(token_result: dict, requested_scopes: list) -> bool:
        """
        Check that the token response contains all requested scopes.
        MSAL returns granted scopes as a space-separated string in the 'scope' key.
        We compare by permission name only (the last path segment), because the
        full URL prefix is stripped by the identity platform.
        """
        granted = set((token_result.get("scope") or "").lower().split())
        for scope in requested_scopes:
            name = scope.split("/")[-1].lower()
            if name not in granted:
                logger.debug(f"Token scope check: '{name}' not in granted={granted}")
                return False
        return True

    def get_token_device_code(
        self,
        scopes: List[str] | None = None,
        device_code_callback: Callable[[Dict], None] | None = None,
    ) -> str:
        """
        Acquire token via device code flow.
        device_code_callback(flow) is called with the MSAL flow dict so the
        caller can display user_code and verification_uri to the user.
        Returns access_token string.
        """
        if scopes is None:
            scopes = DEFAULT_SCOPES

        app = self._build_public_app()

        # Try silent first — but only accept the cached token if it actually
        # contains ALL requested scopes.  A stale token (obtained before new
        # scopes were added to DEFAULT_SCOPES) would cause 403 errors even
        # though authentication technically "succeeded".
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(scopes, account=accounts[0])
            if result and "access_token" in result:
                if self._has_required_scopes(result, scopes):
                    self._save_cache()
                    logger.debug("Token acquired silently")
                    return result["access_token"]
                else:
                    logger.info(
                        "Cached token is missing one or more required scopes — "
                        "re-authenticating via device code to obtain updated permissions."
                    )
                    # Fall through to interactive device code flow below

        # Interactive: device code flow
        flow = app.initiate_device_flow(scopes=scopes)
        if "user_code" not in flow:
            raise AuthError(
                f"Failed to initiate device flow: {flow.get('error_description', flow)}"
            )

        logger.info(f"Device code flow initiated: {flow['message']}")

        if device_code_callback:
            device_code_callback(flow)

        result = app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise AuthError(
                f"Authentication failed: {result.get('error_description', result)}"
            )

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
            raise AuthError(
                f"App-only auth failed: {result.get('error_description', result)}"
            )

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
        """Clear the token cache and scopes hash (full logout)."""
        self._invalidate_cache()
        try:
            if _SCOPES_HASH_PATH.exists():
                _SCOPES_HASH_PATH.unlink()
        except Exception:
            pass

    def has_cached_token(self) -> bool:
        """Check if there is a cached account/token."""
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
