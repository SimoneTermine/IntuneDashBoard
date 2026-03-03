"""
diagnose_apps.py  —  Intune Dashboard standalone diagnostic tool

Runs OUTSIDE the main app to directly query Graph and show exactly what
endpoints return for your apps and install status data.

Usage (from repo root, with venv active):
    python diagnose_apps.py

What it does:
  1. Loads your saved config (tenant_id, client_id) from AppData
  2. Authenticates via device code (same as the main app)
  3. Queries /mobileApps with BOTH v1.0 and beta to show the difference
  4. For each app, tries all install-status endpoints and prints raw results
"""

import sys
import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# ── Minimal bootstrap (no UI, no DB) ─────────────────────────────────────────
from app.logging_config import setup_logging
setup_logging("DEBUG")

import logging
log = logging.getLogger("diagnose")

from app.config import AppConfig
from app.graph.client import GraphClient, GraphError
from app.graph.endpoints import MOBILE_APPS, APP_DEVICE_STATUSES, APP_WIN32_INSTALL_STATES


def hr(title=""):
    print(f"\n{'─' * 70}")
    if title:
        print(f"  {title}")
        print(f"{'─' * 70}")


def query(client, endpoint, api_version="v1.0", params=None, label=""):
    desc = f"[{api_version}] {endpoint}"
    if label:
        desc = f"{label}: {desc}"
    try:
        items = client.get_all(endpoint, params=params, api_version=api_version)
        print(f"  ✅  {desc}  →  {len(items)} items")
        return items
    except GraphError as e:
        print(f"  ❌  {desc}  →  HTTP {e.status_code}: {e}")
        return None
    except Exception as e:
        print(f"  ❌  {desc}  →  {type(e).__name__}: {e}")
        return None


def main():
    cfg = AppConfig()
    print(f"\nTenant : {cfg.tenant_id or '(not set)'}")
    print(f"Client : {cfg.client_id or '(not set)'}")

    if not cfg.tenant_id or not cfg.client_id:
        print("\nERROR: tenant_id or client_id not configured in the app Settings.")
        sys.exit(1)

    print("\nAuthenticating via device code (same flow as main app)...")
    client = GraphClient()
    client.authenticate()
    print("Authenticated OK.\n")

    # ── 1. Compare v1.0 vs beta app count ────────────────────────────────────
    hr("1. /mobileApps — v1.0 vs beta comparison")
    apps_v1   = query(client, MOBILE_APPS, "v1.0",  label="v1.0 ")
    apps_beta = query(client, MOBILE_APPS, "beta",  label="beta")

    if apps_v1 is not None:
        types_v1 = {}
        for a in apps_v1:
            t = a.get("@odata.type", "unknown").split(".")[-1]
            types_v1[t] = types_v1.get(t, 0) + 1
        print(f"\n  v1.0  types: {dict(sorted(types_v1.items()))}")

    if apps_beta is not None:
        types_beta = {}
        for a in apps_beta:
            t = a.get("@odata.type", "unknown").split(".")[-1]
            types_beta[t] = types_beta.get(t, 0) + 1
        print(f"  beta  types: {dict(sorted(types_beta.items()))}")

    # ── 2. Per-app install status probing ─────────────────────────────────────
    apps = apps_beta or apps_v1 or []
    if not apps:
        print("\nNo apps returned — cannot probe install status.")
        return

    hr("2. Per-app install status endpoint probing")
    for app in apps:
        app_id   = app.get("id", "?")
        app_name = app.get("displayName", "?")
        app_type = app.get("@odata.type", "unknown").split(".")[-1]

        print(f"\n  📦  [{app_type}] {app_name!r}  ({app_id})")

        # /deviceStatuses (beta)
        ds = query(client, APP_DEVICE_STATUSES.format(app_id=app_id), "beta",
                   params={"$select": "id,deviceId,deviceName,installState,errorCode,lastSyncDateTime"},
                   label="    /deviceStatuses    ")

        # /deviceInstallStates (beta)
        di = query(client, APP_WIN32_INSTALL_STATES.format(app_id=app_id), "beta",
                   params={"$select": "id,deviceId,deviceName,installState,errorCode,lastSyncDateTime"},
                   label="    /deviceInstallStates")

        # Show first record if any
        for label, result in [("/deviceStatuses", ds), ("/deviceInstallStates", di)]:
            if result:
                print(f"    First {label} record:")
                print(f"      {json.dumps(result[0], default=str, indent=6)}")

    # ── 3. Token scopes check ─────────────────────────────────────────────────
    hr("3. Token — me endpoint (scope verification)")
    try:
        me = client.get("me", api_version="v1.0")
        print(f"  Signed in as: {me.get('userPrincipalName', me.get('id', '?'))}")
    except Exception as e:
        print(f"  me endpoint failed: {e}")

    hr("Diagnosis complete")
    print()


if __name__ == "__main__":
    main()
