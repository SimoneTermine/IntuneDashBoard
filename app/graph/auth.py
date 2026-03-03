"""
Microsoft Graph authentication via MSAL.

Supports:
  A) Delegated  — Device Code Flow (interactive, for admin users)
  B) App-only   — Client Credentials with certificate (service/automation)

Token cache persistence strategy (v1.2.0):
  • Preferred  — DPAPI-encrypted cache via msal-extensions (Windows only).
    File: %APPDATA%\\IntuneDashboard\\msal_cache.bin  (binary/encrypted)
  • Fallback   — Plain SerializableTokenCache (JSON, same path).
    Used when msal-extensions is unavailable or DPAPI init fails.

Scope change detection:
  When DEFAULT_SCOPES changes between versions, the stored hash in
  msal_scopes.json is compared on startup.  Mismatch → cache cleared →
  device code re-auth on next sync.

ReadWrite vs Read scope hierarchy:
  Azure AD issues DeviceManagementConfiguration.ReadWrite.All and
  DeviceManagementConfiguration.Read.All as separate scope strings.
  _has_required_scopes() treats a granted ReadWrite.All as satisfying a
  Read.All requirement, preventing repeated device code prompts when
  the tenant only consented ReadWrite.All.
"""

import hashlib
import json
import logging
import webbrowser
from pathlib import Path
from typing import Optional, List, Dict, Callable
from urllib.parse import quote

import msal

from app.config import AppConfig, MSAL_CACHE_PATH, DEFAULT_SCOPES

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
_SCOPES_HASH_PATH = MSAL_CACHE_PATH.parent / "msal_scopes.json"

# ── DPAPI availability probe ──────────────────────────────────────────────────
try:
    from msal_extensions import build_encrypted_persistence, PersistedTokenCache  # type: ignore
    _DPAPI_AVAILABLE = True
    logger.debug("msal-extensions found — DPAPI-encrypted token cache enabled")
except Exception:
    _DPAPI_AVAILABLE = False
    logger.debug("msal-extensions not available — using plain token cache")


# ─────────────────────────────────────────────────────────────────────────────
class AuthError(Exception):
    pass


class AdminConsentRequiredError(AuthError):
    """Raised when the Graph response indicates missing admin consent."""
    pass


def _scopes_hash(scopes: list) -> str:
    """Stable hash of a sorted list of scope strings."""
    key = "|".join(sorted(scopes))
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def admin_consent_url(client_id: str, tenant_id: str) -> str:
    """
    Build the Azure AD admin-consent URL for this app.
    If tenant_id is empty or 'common', uses 'common' (shows a tenant picker).
    """
    tid = tenant_id.strip() if tenant_id and tenant_id.strip() not in ("", "common") else "common"
    redirect = quote("https://login.microsoftonline.com/common/oauth2/nativeclient", safe="")
    return (
        f"https://login.microsoftonline.com/{tid}/adminconsent"
        f"?client_id={client_id}&redirect_uri={redirect}"
    )


def open_admin_consent_page(client_id: str = "", tenant_id: str = "") -> str:
    """Open the admin-consent URL in the default browser and return the URL."""
    cfg = AppConfig()
    cid = client_id or cfg.client_id
    tid = tenant_id or cfg.tenant_id
    url = admin_consent_url(cid, tid)
    webbrowser.open(url)
    logger.info(f"Admin consent page opened: {url}")
    return url


# ─────────────────────────────────────────────────────────────────────────────
class MSALAuth:
    """MSAL authentication wrapper (singleton via get_auth())."""

    def __init__(self):
        self._app: Optional[
            msal.PublicClientApplication | msal.ConfidentialClientApplication
        ] = None
        self._using_dpapi: bool = False
        self._setup_cache()
        self._check_scope_change()

    # ── Cache setup ───────────────────────────────────────────────────────────

    def _setup_cache(self):
        """
        Initialise the token cache.

        Priority:
          1. DPAPI-encrypted PersistedTokenCache (msal-extensions)  — Windows only
          2. Plain SerializableTokenCache with manual load/save       — fallback

        If the cache file exists but is plain JSON (legacy) and we are switching
        to DPAPI, we remove the plain file so the user re-authenticates once with
        the encrypted store.
        """
        if _DPAPI_AVAILABLE:
            try:
                persistence = build_encrypted_persistence(str(MSAL_CACHE_PATH))
                self._cache = PersistedTokenCache(persistence)
                self._using_dpapi = True
                logger.debug("Token cache: DPAPI-encrypted (msal-extensions)")

                # If an old plain-JSON cache exists, clear it so it doesn't
                # interfere.  The user will re-auth once after upgrading.
                if MSAL_CACHE_PATH.exists():
                    try:
                        raw = MSAL_CACHE_PATH.read_bytes()
                        json.loads(raw)          # succeeds → it's plain JSON
                        MSAL_CACHE_PATH.unlink()
                        logger.info(
                            "Removed legacy plain-text token cache; "
                            "re-authentication required once."
                        )
                    except (ValueError, UnicodeDecodeError):
                        # File is binary/encrypted — already the right format
                        pass
                return
            except Exception as e:
                logger.warning(f"DPAPI cache init failed ({e}), falling back to plain cache")

        # Fallback: plain SerializableTokenCache
        self._cache = msal.SerializableTokenCache()
        self._using_dpapi = False
        self._load_plain_cache()
        logger.debug("Token cache: plain SerializableTokenCache")

    def _load_plain_cache(self):
        """Load plain-JSON cache from disk (only used when DPAPI is unavailable)."""
        if MSAL_CACHE_PATH.exists():
            try:
                with open(MSAL_CACHE_PATH, "r", encoding="utf-8") as f:
                    self._cache.deserialize(f.read())
                logger.debug("MSAL plain cache loaded from disk")
            except Exception as e:
                logger.warning(f"Could not load MSAL cache: {e}")

    def _save_plain_cache(self):
        """Persist plain-JSON cache to disk (only used when DPAPI is unavailable)."""
        if not self._using_dpapi and self._cache.has_state_changed:
            try:
                MSAL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                with open(MSAL_CACHE_PATH, "w", encoding="utf-8") as fh:
                    fh.write(self._cache.serialize())
                # Restrict permissions: owner-only read/write (best-effort on Windows)
                try:
                    import stat
                    MSAL_CACHE_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)
                except Exception:
                    pass
                logger.debug("MSAL plain cache saved to disk")
            except Exception as e:
                logger.warning(f"Could not save MSAL cache: {e}")

    def _save_cache(self):
        """Save token cache + scopes hash after successful auth."""
        self._save_plain_cache()   # no-op when using DPAPI (auto-persisted)
        self._save_scopes_hash()

    # ── Scope change detection ────────────────────────────────────────────────

    def _check_scope_change(self):
        """
        Compare the hash of DEFAULT_SCOPES against the stored hash.
        If different (or no hash exists), clear the cache so the user is
        re-prompted for a new consent on the next sync / Test Connection.
        """
        current_hash = _scopes_hash(DEFAULT_SCOPES)
        stored_hash: Optional[str] = None

        try:
            if _SCOPES_HASH_PATH.exists():
                data = json.loads(_SCOPES_HASH_PATH.read_text(encoding="utf-8"))
                stored_hash = data.get("hash")
        except Exception as e:
            logger.debug(f"Could not read scopes hash: {e}")

        if stored_hash is not None and stored_hash != current_hash:
            logger.warning(
                "Required Graph API permissions have changed since last login. "
                "Clearing token cache — you will be prompted to re-authenticate "
                "with the updated permissions on next sync."
            )
            self._invalidate_cache()
        elif stored_hash is None and MSAL_CACHE_PATH.exists():
            logger.info(
                "Scope tracking introduced — clearing token cache to ensure "
                "all required permissions are granted on next authentication."
            )
            self._invalidate_cache()

        self._save_scopes_hash()

    def _save_scopes_hash(self):
        """Persist current DEFAULT_SCOPES hash."""
        try:
            _SCOPES_HASH_PATH.write_text(
                json.dumps({"hash": _scopes_hash(DEFAULT_SCOPES), "scopes": DEFAULT_SCOPES}),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug(f"Could not save scopes hash: {e}")

    def _invalidate_cache(self):
        """
        Delete the on-disk token cache file and reset the in-memory cache.
        Does NOT remove the msal_scopes.json — that is handled by sign_out().
        """
        # Delete file
        try:
            if MSAL_CACHE_PATH.exists():
                MSAL_CACHE_PATH.unlink()
        except Exception as e:
            logger.warning(f"Could not delete cache file: {e}")

        # Reset in-memory cache
        if _DPAPI_AVAILABLE and self._using_dpapi:
            try:
                persistence = build_encrypted_persistence(str(MSAL_CACHE_PATH))
                self._cache = PersistedTokenCache(persistence)
            except Exception:
                self._cache = msal.SerializableTokenCache()
                self._using_dpapi = False
        else:
            self._cache = msal.SerializableTokenCache()

        self._app = None
        logger.info("Token cache cleared")

    # ── MSAL app builders ─────────────────────────────────────────────────────

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

    # ── Scope check ───────────────────────────────────────────────────────────

    @staticmethod
    def _has_required_scopes(token_result: dict, requested_scopes: list) -> bool:
        """
        Return True only when the token covers every requested scope.

        Rules:
        • Comparison is case-insensitive on the permission name (last URL segment).
        • ReadWrite.All satisfies a Read.All requirement for the same resource
          namespace.  Example: DeviceManagementConfiguration.ReadWrite.All
          is accepted when DeviceManagementConfiguration.Read.All is requested.
          This prevents repeated device code prompts when the tenant consented
          to ReadWrite.All but the scope list also includes Read.All.
        • openid / profile / offline_access are always skipped (OIDC internals).
        """
        _OIDC = {"openid", "profile", "offline_access", "email"}

        # MSAL may return scopes as full URIs OR short names — normalise both.
        # e.g. "https://graph.microsoft.com/DeviceManagementApps.Read.All"
        #   → also adds "devicemanagementapps.read.all" to the granted set.
        raw_granted = (token_result.get("scope") or "").lower().split()
        granted: set[str] = set()
        for s in raw_granted:
            granted.add(s)
            granted.add(s.split("/")[-1])   # last path segment = short permission name

        for scope in requested_scopes:
            name = scope.split("/")[-1].lower()
            if name in _OIDC:
                continue
            if name in granted:
                continue
            # ReadWrite.All ⊇ Read.All for the same resource prefix
            if name.endswith(".read.all"):
                prefix = name[: -len(".read.all")]
                if f"{prefix}.readwrite.all" in granted:
                    continue
            logger.debug(f"Scope check: '{name}' not satisfied by granted={sorted(granted)}")
            return False
        return True

    # ── Token acquisition ─────────────────────────────────────────────────────

    def get_token_device_code(
        self,
        scopes: Optional[List[str]] = None,
        device_code_callback: Optional[Callable[[Dict], None]] = None,
    ) -> str:
        """
        Acquire an access token — silent-first, device code as fallback.

        Flow:
          1. Try acquire_token_silent with the first cached account.
          2. If the silent token covers all required scopes → return it.
          3. Otherwise (no account / interaction_required / missing scopes)
             → initiate device code flow ONCE.
          4. After successful device code → save cache + scopes hash.
        """
        if scopes is None:
            scopes = DEFAULT_SCOPES

        app = self._build_public_app()

        # ── Silent path ───────────────────────────────────────────────────────
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(scopes, account=accounts[0])
            if result and "access_token" in result:
                if self._has_required_scopes(result, scopes):
                    self._save_cache()
                    logger.debug("Token acquired silently (cache hit)")
                    return result["access_token"]
                else:
                    logger.info(
                        "Cached token is missing one or more required scopes — "
                        "initiating device code flow for incremental consent."
                    )
            else:
                err = (result or {}).get("error", "")
                if err in ("interaction_required", "consent_required"):
                    logger.info(f"Silent token failed with '{err}' — device code required.")
                else:
                    logger.debug(f"Silent token unavailable (error={err!r}) — device code required.")

        # ── Device code path ──────────────────────────────────────────────────
        flow = app.initiate_device_flow(scopes=scopes)
        if "user_code" not in flow:
            raise AuthError(
                f"Failed to initiate device code flow: "
                f"{flow.get('error_description', flow)}"
            )

        # Do NOT log the user_code value itself
        logger.info("Device code flow initiated — waiting for user sign-in")

        if device_code_callback:
            device_code_callback(flow)

        result = app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            err_desc = result.get("error_description", "") or ""
            err_code = result.get("error", "") or ""
            # Detect admin consent requirement
            if "AADSTS65001" in err_desc or err_code == "consent_required":
                raise AdminConsentRequiredError(
                    "Admin consent is required for one or more permissions. "
                    "Ask a tenant Global Administrator to grant consent via the "
                    "Admin Consent URL in Settings."
                )
            raise AuthError(
                f"Authentication failed: {err_desc or result}"
            )

        self._save_cache()
        logger.info("Authentication successful via device code")
        return result["access_token"]


    def get_token_app_only(self, scopes: Optional[List[str]] = None) -> str:
        """Acquire token via client credentials (app-only / service account)."""
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
        scopes: Optional[List[str]] = None,
        device_code_callback: Optional[Callable] = None,
    ) -> str:
        """Return an access token using the configured auth mode."""
        cfg = AppConfig()
        if cfg.auth_mode == "app_only":
            return self.get_token_app_only(scopes)
        return self.get_token_device_code(scopes, device_code_callback)

    # ── Sign-out / cache clearing ─────────────────────────────────────────────

    def sign_out(self) -> None:
        """
        Full sign-out:
          1. Remove all MSAL accounts from the cache.
          2. Delete the on-disk cache file (encrypted or plain).
          3. Delete msal_scopes.json.
          4. Reset the in-memory state.

        After sign_out(), the next call to get_token() will initiate a
        fresh device code flow.
        """
        # 1. Remove accounts via MSAL (best-effort — may fail if app build fails)
        try:
            app = self._build_public_app()
            for account in app.get_accounts():
                try:
                    app.remove_account(account)
                    logger.debug(f"Removed MSAL account: {account.get('username', '?')}")
                except Exception as e:
                    logger.debug(f"Could not remove account: {e}")
        except Exception as e:
            logger.debug(f"Could not build app for account removal: {e}")

        # 2 & 3. Delete cache files
        for path in [MSAL_CACHE_PATH, _SCOPES_HASH_PATH]:
            if path.exists():
                try:
                    path.unlink()
                    logger.info(f"Deleted cache file: {path.name}")
                except Exception as e:
                    logger.warning(f"Could not delete {path.name}: {e}")

        # 4. Reset in-memory state
        self._app = None
        if _DPAPI_AVAILABLE:
            try:
                persistence = build_encrypted_persistence(str(MSAL_CACHE_PATH))
                self._cache = PersistedTokenCache(persistence)
                self._using_dpapi = True
            except Exception:
                self._cache = msal.SerializableTokenCache()
                self._using_dpapi = False
        else:
            self._cache = msal.SerializableTokenCache()

        logger.info("Sign-out complete — next sync will require re-authentication")

    def clear_cache(self) -> None:
        """
        Alias for sign_out() — kept for backward compatibility with
        settings_page.py and any other callers.
        """
        self.sign_out()

    # ── Status helpers ────────────────────────────────────────────────────────

    def has_cached_token(self) -> bool:
        """Return True if there is at least one cached account."""
        try:
            app = self._build_public_app()
            return len(app.get_accounts()) > 0
        except Exception:
            return False

    def cache_type(self) -> str:
        """Return 'DPAPI' or 'plain' for display in UI / logs."""
        return "DPAPI" if self._using_dpapi else "plain"


# ── Singleton ─────────────────────────────────────────────────────────────────

_auth_instance: Optional[MSALAuth] = None


def get_auth() -> MSALAuth:
    global _auth_instance
    if _auth_instance is None:
        _auth_instance = MSALAuth()
    return _auth_instance