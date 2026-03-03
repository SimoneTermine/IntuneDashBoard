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
setup_logging("INFO")

import logging
log = logging.getLogger("diagnose")

from app.config import AppConfig
from app.graph.client import GraphClient, GraphError
from app.graph.endpoints import (
    MOBILE_APPS,
    APP_STATUS_OVERVIEW_REPORT,
    APP_DEVICE_INSTALL_STATUS_REPORT,
)


def hr(title=""):
    print(f"\n{'─' * 70}")
    if title:
        print(f"  {title}")
        print(f"{'─' * 70}")


def device_code_prompt(flow):
    uri  = flow.get("verification_uri", "https://microsoft.com/devicelogin")
    code = flow.get("user_code", "?")
    print(f"\n{'=' * 70}")
    print(f"  Apri nel browser: {uri}")
    print(f"  Codice:           {code}")
    print(f"{'=' * 70}\n")


def parse_report(resp: dict) -> list[dict]:
    """Converte {Schema, Values} in lista di dict."""
    schema = resp.get("Schema", [])
    values = resp.get("Values", [])
    cols   = [s["Column"] for s in schema]
    return [dict(zip(cols, row)) for row in values]


def main():
    cfg = AppConfig()
    print(f"\nTenant : {cfg.tenant_id or '(not set)'}")
    print(f"Client : {cfg.client_id or '(not set)'}")
    if not cfg.tenant_id or not cfg.client_id:
        print("ERROR: configura tenant_id e client_id nelle impostazioni.")
        sys.exit(1)

    print("\nAutenticazione...")
    client = GraphClient()
    try:
        client.authenticate(device_code_callback=device_code_prompt)
    except Exception as e:
        print(f"Autenticazione fallita: {e}")
        sys.exit(1)
    print("Autenticato OK.")

    # -- 1. Lista app ---------------------------------------------------------
    hr("1. App dal tenant (beta, no $select)")
    apps = list(client.get_paged(MOBILE_APPS, api_version="beta"))
    print(f"  Totale app: {len(apps)}")
    types: dict[str, int] = {}
    for a in apps:
        t = a.get("@odata.type", "?").split(".")[-1]
        types[t] = types.get(t, 0) + 1
    for t, n in sorted(types.items()):
        print(f"    {t}: {n}")

    # -- 2. Reports API per ogni app ------------------------------------------
    hr("2. Reports API (getAppStatusOverviewReport + getDeviceInstallStatusReport)")

    for app in apps:
        app_id   = app.get("id", "")
        app_type = app.get("@odata.type", "?").split(".")[-1]
        name     = app.get("displayName", "?")
        print(f"\n  [{app_type}] {name!r}  ({app_id})")

        # Overview
        try:
            resp = client.post(
                APP_STATUS_OVERVIEW_REPORT,
                json={"filter": f"(ApplicationId eq '{app_id}')"},
                api_version="beta",
            )
            rows = parse_report(resp)
            if rows:
                r = rows[0]
                print(f"    Overview: installed={r.get('InstalledDeviceCount',0)} "
                      f"failed={r.get('FailedDeviceCount',0)} "
                      f"pending={r.get('PendingInstallDeviceCount',0)} "
                      f"notInstalled={r.get('NotInstalledDeviceCount',0)} "
                      f"notApplicable={r.get('NotApplicableDeviceCount',0)}")
            else:
                print("    Overview: 0 righe (nessun dato ancora)")
        except GraphError as e:
            print(f"    Overview: HTTP {e.status_code} -- {e.raw or e}")
        except Exception as e:
            print(f"    Overview: errore -- {e}")

        # Per-device
        try:
            resp = client.post(
                APP_DEVICE_INSTALL_STATUS_REPORT,
                json={"filter": f"(ApplicationId eq '{app_id}')", "top": 5, "orderBy": []},
                api_version="v1.0",
            )
            rows = parse_report(resp)
            print(f"    Per-device: {len(rows)} righe")
            if rows:
                r = rows[0]
                print(f"      Esempio: device={r.get('DeviceName','?')} "
                      f"state={r.get('InstallState','?')} "
                      f"user={r.get('UserName', r.get('UPN','?'))}")
        except GraphError as e:
            print(f"    Per-device: HTTP {e.status_code} -- {e.raw or e}")
        except Exception as e:
            print(f"    Per-device: errore -- {e}")

    hr("Diagnosi completata")
    print()


if __name__ == "__main__":
    main()