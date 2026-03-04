# Intune Dashboard

A local desktop application for Microsoft Intune administrators.
Connects to Microsoft Graph API, caches data in a local SQLite database,
and provides a rich UI for device management, policy exploration, and governance.

**Current version: 1.3.1**

---

## Features

| Page | Description |
|---|---|
| **Overview** | KPI cards, compliance charts, recent sync log |
| **Device Explorer** | Search, filter, sort devices; right-click context menu |
| **Policy Explorer** | Compliance, config, Settings Catalog, Endpoint Security, apps |
| **App Ops** | KPI strip, segmented state bar, App Catalog (overview counts), Install Log, Error Analysis, Device Drill-down. Falls back to aggregated data when the Reports API beta endpoint is not available for the tenant |
| **Governance** | Point-in-time snapshots, drift detection between snapshots |
| **Explainability** | Full reasoning chain: why a policy applies to a device |
| **Group Usage** | Objects assigned to a group, dead-assignment detection |
| **Graph Query Lab** | Ad-hoc Graph API tool: GET with paged collection, POST/PATCH/DELETE with JSON body editor, live JSON validation, preset library |
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
git clone https://github.com/SimoneTermine/IntuneDashBoard.git
cd IntuneDashBoard

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

---

## App Ops — Data Sources

App Ops uses two Graph API endpoints for install status data:

| Endpoint | API | What it provides |
|---|---|---|
| `getAppStatusOverviewReport` | beta | Aggregated counts per app (always works) |
| `getDeviceInstallStatusReport` | beta | Per-device rows for Install Log and Drill-down |

If your tenant does not support `getDeviceInstallStatusReport` (HTTP 400 returned),
the **App Catalog** and **KPI cards** remain fully accurate using the overview data.
**Install Log** and **Device Drill-down** will show aggregated overview rows with a
yellow banner explaining the limitation.

---

## Graph Query Lab

The Graph Query Lab supports all four HTTP methods:

| Method | Use case |
|---|---|
| **GET** | Retrieve resources; optionally collect all pages automatically |
| **POST** | Reports API (e.g. `getAppStatusOverviewReport`), create resources |
| **PATCH** | Update resource properties |
| **DELETE** | Remove resources |

The JSON body editor includes live syntax validation and a Format button.
A preset library provides one-click access to the most common endpoints.

---

## Logs

| File | Contents |
|---|---|
| `collector.log` | Full sync engine trace (devices, policies, apps, groups) |
| `app_ops.log` | App install status subsystem (Reports API calls, per-app detail) |

Both rotate at 2 MB with date-stamped archives (SCCM-style handler).
