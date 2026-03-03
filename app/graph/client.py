"""
Microsoft Graph HTTP client.
Handles authentication, pagination, retry with backoff, and rate limiting (HTTP 429).
app/graph/client.py — v1.2.2
"""

import logging
import time
import json

from typing import Any, Dict, Generator, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.config import GRAPH_BASE_URL_V1, GRAPH_BASE_URL_BETA
from app.graph.auth import get_auth, AuthError, AdminConsentRequiredError

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF = 2  # seconds base
PAGE_SIZE = 999    # max allowed by Graph for most endpoints


class GraphError(Exception):
    def __init__(self, message: str, status_code: int = 0, raw: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.raw = raw


class GraphClient:
    """
    Authenticated Graph API client.
    - Automatically refreshes tokens
    - Handles pagination (@odata.nextLink)
    - Handles HTTP 429 rate limiting (Retry-After header)
    - Retry on transient 5xx errors
    """

    def __init__(self):
        self._token: Optional[str] = None
        self._session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=MAX_RETRIES,
            backoff_factor=RETRY_BACKOFF,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        return session

    def _ensure_token(self, device_code_callback=None):
        if not self._token:
            logger.debug("Acquiring access token...")
            self._token = get_auth().get_token(device_code_callback=device_code_callback)

    def authenticate(self, device_code_callback=None):
        """Explicitly authenticate and cache token."""
        self._token = get_auth().get_token(device_code_callback=device_code_callback)
        logger.info("GraphClient authenticated successfully")

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "ConsistencyLevel": "eventual",
        }

    def _request(
        self,
        method: str,
        url: str,
        params: Dict | None = None,
        json_body: Dict | None = None,
        retry_on_401: bool = True,
    ) -> Dict:
        """Execute a single HTTP request with rate limit and error handling."""
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = self._session.request(
                    method,
                    url,
                    headers=self._headers(),
                    params=params,
                    json=json_body,
                    timeout=60,
                )
            except requests.RequestException as e:
                raise GraphError(f"Network error: {e}") from e

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 5))
                logger.warning(f"Rate limited (429). Waiting {retry_after}s before retry...")
                time.sleep(retry_after + 1)
                continue

            if resp.status_code == 401 and retry_on_401:
                logger.info("Token expired or invalid (401). Re-authenticating...")
                self._token = None
                self._ensure_token()
                retry_on_401 = False
                continue

            if resp.status_code == 403:
                # Check for admin consent required
                try:
                    err_body = resp.json().get("error", {})
                    err_code = err_body.get("code", "")
                    err_msg  = err_body.get("message", resp.text)
                    if "AADSTS65001" in err_msg or "consent_required" in err_code.lower():
                        raise AdminConsentRequiredError(
                            f"Admin consent required. Grant consent via the Admin Consent "
                            f"Page in Settings, then retry.\n\nDetail: {err_msg}"
                        )
                except AdminConsentRequiredError:
                    raise
                except Exception:
                    pass
                raise GraphError(
                    f"Access denied (403): {resp.text}. Check app permissions.",
                    status_code=403,
                    raw=resp.text,
                )

            if resp.status_code == 404:
                raise GraphError(
                    f"Resource not found (404): {url}",
                    status_code=404,
                )

            if not resp.ok:
                try:
                    err = resp.json().get("error", {})
                    msg = f"{err.get('code', 'unknown')}: {err.get('message', resp.text)}"
                except Exception:
                    msg = resp.text
                raise GraphError(
                    f"Graph API error {resp.status_code}: {msg}",
                    status_code=resp.status_code,
                    raw=resp.text,
                )

            if resp.status_code == 204:
                return {}

            try:
                return resp.json()
            except Exception:
                return json.loads(resp.content.decode("utf-8-sig"))

        raise GraphError(f"Max retries exceeded for {url}")

    # ─────────────────────────────────────────────────────────────────────────
    # Public HTTP helpers
    # ─────────────────────────────────────────────────────────────────────────

    def get(self, endpoint: str, params: Dict | None = None, api_version: str = "v1.0") -> Dict:
        """GET a single resource."""
        base = GRAPH_BASE_URL_V1 if api_version == "v1.0" else GRAPH_BASE_URL_BETA
        url = endpoint if endpoint.startswith("http") else f"{base}/{endpoint}"
        self._ensure_token()
        return self._request("GET", url, params=params)

    def post(
        self,
        endpoint: str,
        json: Dict | None = None,
        api_version: str = "v1.0",
        expected_status: int = 200,
    ) -> Dict:
        """
        POST to a Graph endpoint.

        expected_status is informational (the _request method already handles 204 → {}).
        Returns the parsed JSON body, or {} for 204 No Content responses.
        """
        base = GRAPH_BASE_URL_V1 if api_version == "v1.0" else GRAPH_BASE_URL_BETA
        url = endpoint if endpoint.startswith("http") else f"{base}/{endpoint}"
        self._ensure_token()
        return self._request("POST", url, json_body=json)

    def get_paged(
        self,
        endpoint: str,
        params: Dict | None = None,
        api_version: str = "v1.0",
        max_items: int | None = None,
    ) -> Generator[Dict, None, None]:
        """
        Generator that yields each item from a paged Graph collection.
        Follows @odata.nextLink automatically.
        """
        base = GRAPH_BASE_URL_V1 if api_version == "v1.0" else GRAPH_BASE_URL_BETA
        url = endpoint if endpoint.startswith("http") else f"{base}/{endpoint}"

        _params = {"$top": PAGE_SIZE}
        if params:
            _params.update(params)

        self._ensure_token()
        total_yielded = 0

        while url:
            data = self._request("GET", url, params=_params if url.startswith(base) else None)
            items = data.get("value", [])

            for item in items:
                yield item
                total_yielded += 1
                if max_items and total_yielded >= max_items:
                    return

            url = data.get("@odata.nextLink")
            _params = None  # params already embedded in nextLink

    def get_all(
        self,
        endpoint: str,
        params: Dict | None = None,
        api_version: str = "v1.0",
    ) -> List[Dict]:
        """Collect all items from a paged endpoint into a list."""
        return list(self.get_paged(endpoint, params=params, api_version=api_version))

    # ─────────────────────────────────────────────────────────────────────────
    # Connection test
    # ─────────────────────────────────────────────────────────────────────────

    def test_connection(self) -> Dict[str, Any]:
        """
        Test Graph connectivity by fetching the tenant's organization object.
        Returns dict with:
          'ok'      — True if the call succeeded
          'details' — human-readable result string
        """
        try:
            self._ensure_token()
            data = self.get("organization?$select=displayName,id")
            orgs = data.get("value", [])
            name = orgs[0].get("displayName", "unknown") if orgs else "unknown"
            return {"ok": True, "details": f"Connected to tenant: {name}"}
        except AdminConsentRequiredError as e:
            raise  # re-raise so settings_page can show the consent button
        except AuthError as e:
            return {"ok": False, "details": f"Auth error: {e}"}
        except GraphError as e:
            return {"ok": False, "details": f"Graph error: {e}"}
        except Exception as e:
            return {"ok": False, "details": f"Unexpected error: {e}"}


# ─────────────────────────────────────────────────────────────────────────────
# Singleton helpers
# ─────────────────────────────────────────────────────────────────────────────

_client: Optional[GraphClient] = None


def get_client() -> GraphClient:
    global _client
    if _client is None:
        _client = GraphClient()
    return _client


def reset_client():
    """Reset the singleton client (e.g. after config change or sign-out)."""
    global _client
    _client = None
