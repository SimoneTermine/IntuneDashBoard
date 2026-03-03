# Intune Dashboard

A local desktop application for Microsoft Intune administrators.
Connects to Microsoft Graph API, caches data in a local SQLite database,
and provides a rich UI for device management, policy exploration, and governance.

**Current version: 1.2.4**

---

## Features

| Page | Description |
|---|---|
| **Overview** | KPI cards, compliance charts, recent sync log |
| **Device Explorer** | Search, filter, sort devices; right-click context menu |
| **Policy Explorer** | Compliance, config, Settings Catalog, Endpoint Security, apps |
| **App Ops** | Deployment state, top failures, install error clustering |
| **Governance** | Point-in-time snapshots, drift detection between snapshots |
| **Explainability** | Full reasoning chain: why a policy applies to a device |
| **Group Usage** | Objects assigned to a group, dead-assignment detection |
| **Graph Query Lab** | Ad-hoc Graph API tool with paged collection support |
| **Settings** | Tenant / auth config, scheduler, storage paths |

---

## Requirements

- Python **3.10+**
- PySide6, msal, msal-extensions, sqlalchemy, requests, apscheduler

```bash
pip install -r requirements.txt
```

---

## Entra App Registration

1. **Entra Admin Center → App registrations → New registration** (Single tenant)
2. **API permissions → Microsoft Graph → Delegated** — add all of the following:

| Permission | Required for |
|---|---|
| `DeviceManagementManagedDevices.Read.All` | Devices, compliance, force sync |
| `DeviceManagementApps.Read.All` | Apps, install status |
| `Group.Read.All` | Group targeting, dead-assignment detection |
| `User.Read.All` | User memberships, device–user correlation |
| `Device.Read.All` | Device group memberships |
| `DeviceManagementRBAC.Read.All` | RBAC scope tags |

3. **Grant admin consent** for your tenant.
4. **Authentication → Add a platform → Mobile and desktop applications**
   Enable redirect URI: `https://login.microsoftonline.com/common/oauth2/nativeclient`
5. **Advanced settings → Allow public client flows → Yes**

---

## Quick Start

```bash
git clone https://github.com/yourorg/intune-dashboard.git
cd intune-dashboard

python -m venv .venv
.venv\Scripts\activate        # Windows

pip install -r requirements.txt
python main.py
```

### First-time setup

1. Settings → enter **Tenant ID** and **Client ID** (click 👁 to reveal masked fields)
2. **Auth Mode**: `device_code` (recommended for interactive admin use)
3. Click **Save Settings**
4. Click **Test Graph Connection**
5. A dialog appears with a URL and a code — open the URL in a browser,
   enter the code, and sign in with an admin account
6. The dialog closes automatically once authentication succeeds
7. Click **Sync Now** in the sidebar

---

## Authentication & Token Cache

- **Cache location**: `%APPDATA%\IntuneDashboard\msal_cache.bin`
- **Encryption**: DPAPI via msal-extensions (Windows, bound to your user account).
  Falls back to plain JSON if msal-extensions is not installed.
- **Sign out**: Settings → *Sign out / Clear Token Cache* removes the cache and
  forces a fresh device code sign-in on next sync.
- **Admin consent**: if you see `403 / AADSTS65001`, use
  Settings → *Open Admin Consent Page* — a Global Administrator must grant consent.

---

## Log Files

Logs are written to `%APPDATA%\IntuneDashboard\logs\`.

| File | Content |
|---|---|
| `intune_dashboard.log` | Everything (root logger) |
| `graph.log` | Graph API calls and auth events |
| `collector.log` | Sync engine and data collectors |
| `db.log` | Database operations |
| `ui.log` | UI events |
| `app_ops.log` | App Ops page: KPI/drill-down/filter queries, per-app sync stats, DB write errors |

**Rotation** (SCCM-style): when a log file reaches **2 MB** it is automatically
renamed to `<name>_<YYYY-MM-DD>.log` (e.g. `intune_dashboard_2026-03-03.log`) and
a fresh `<name>.log` is started. If that dated archive already exists, a counter
is appended: `_1`, `_2`, etc.

---

## Data Storage

| Path | Content |
|---|---|
| `%APPDATA%\IntuneDashboard\intune_dashboard.db` | Local SQLite cache |
| `%APPDATA%\IntuneDashboard\msal_cache.bin` | Encrypted MSAL token cache |
| `%APPDATA%\IntuneDashboard\config.json` | Application settings |
| `%APPDATA%\IntuneDashboard\exports\` | CSV / JSON / PDF exports |

---

## Demo Mode

Enable **Demo Mode** in Settings to explore the UI without real credentials.
A synthetic dataset of devices, policies, and apps is loaded from
`app/demo/demo_data.py`. Disable before connecting to a real tenant.

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Building a Standalone Executable

```bash
pyinstaller intune_dashboard.spec
```

Output in `dist/IntuneDashboard/`.
