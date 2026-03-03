"""
diagnose_apps.py  --  Intune Dashboard standalone diagnostic tool  v1.2.6

Runs OUTSIDE the main app to directly query Graph and show exactly what
endpoints return for your apps and install status data.

Usage (from repo root, with venv active):
    python diagnose_apps.py

What it does:
  1. Loads your saved config from AppData
  2. Authenticates via device code -- PRINTS the code to the console
  3. Compares /mobileApps v1.0 vs beta (app type counts)
  4. Probes /deviceStatuses and /deviceInstallStates for every app
  5. Shows the raw Graph error message for 400s so the actual reason is visible
"""

import sys
import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

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
        print(f"  OK  {desc}  ->  {len(items)} items")
        return items
    except GraphError as e:
        # Print the full raw response so the actual Graph error message is visible
        raw_msg = ""
        if e.raw:
            try:
                raw_msg = json.dumps(e.raw, indent=4)
            except Exception:
                raw_msg = str(e.raw)
        print(f"  ERR {desc}  ->  HTTP {e.status_code}: {e}")
        if raw_msg:
            print(f"      Raw response:\n{raw_msg}")
        return None
    except Exception as e:
        print(f"  ERR {desc}  ->  {type(e).__name__}: {e}")
        return None


def device_code_prompt(flow):
    """Print device code to console so the user can sign in."""
    uri  = flow.get("verification_uri", "https://microsoft.com/devicelogin")
    code = flow.get("user_code", "?")
    print(f"\n{'=' * 70}")
    print(f"  ACTION REQUIRED: Open this URL in your browser:")
    print(f"    {uri}")
    print(f"\n  Enter this code: {code}")
    print(f"{'=' * 70}\n")


def main():
    cfg = AppConfig()
    print(f"\nTenant : {cfg.tenant_id or '(not set)'}")
    print(f"Client : {cfg.client_id or '(not set)'}")

    if not cfg.tenant_id or not cfg.client_id:
        print("\nERROR: tenant_id or client_id not configured in the app Settings.")
        sys.exit(1)

    print("\nAuthenticating (device code flow if needed)...")
    client = GraphClient()
    try:
        client.authenticate(device_code_callback=device_code_prompt)
    except Exception as e:
        print(f"\nAuthentication failed: {e}")
        sys.exit(1)
    print("Authenticated OK.")

    # ── 1. Compare v1.0 vs beta ───────────────────────────────────────────────
    hr("1. /mobileApps -- v1.0 vs beta comparison")
    apps_v1   = query(client, MOBILE_APPS, "v1.0",  label="v1.0 ")
    apps_beta = query(client, MOBILE_APPS, "beta",  label="beta ")

    for label, apps in [("v1.0", apps_v1), ("beta", apps_beta)]:
        if apps is not None:
            types = {}
            for a in apps:
                t = a.get("@odata.type", "unknown").split(".")[-1]
                types[t] = types.get(t, 0) + 1
            print(f"  {label} types: {dict(sorted(types.items()))}")

    # ── 2. Per-app install status ─────────────────────────────────────────────
    apps = apps_beta or apps_v1 or []
    if not apps:
        print("\nNo apps returned -- cannot probe install status.")
        return

    hr("2. Per-app install status endpoint probing")
    for app in apps:
        app_id   = app.get("id", "?")
        app_name = app.get("displayName", "?")
        app_type = app.get("@odata.type", "unknown").split(".")[-1]

        print(f"\n  [{app_type}] {app_name!r}  ({app_id})")

        ds = query(client, APP_DEVICE_STATUSES.format(app_id=app_id), "beta",
                   params={"$select": "id,deviceId,deviceName,installState,errorCode,lastSyncDateTime"},
                   label="    /deviceStatuses    ")
        di = query(client, APP_WIN32_INSTALL_STATES.format(app_id=app_id), "beta",
                   params={"$select": "id,deviceId,deviceName,installState,errorCode,lastSyncDateTime"},
                   label="    /deviceInstallStates")

        for lbl, result in [("/deviceStatuses", ds), ("/deviceInstallStates", di)]:
            if result:
                print(f"    First {lbl} record:")
                print(f"      {json.dumps(result[0], default=str, indent=6)}")

    # ── 3. Token identity ─────────────────────────────────────────────────────
    hr("3. Token identity (/me)")
    try:
        me = client.get("me", api_version="v1.0")
        print(f"  Signed in as: {me.get('userPrincipalName', me.get('id', '?'))}")
    except Exception as e:
        print(f"  /me failed: {e}")

    hr("Diagnosis complete")
    print()


if __name__ == "__main__":
    main()
