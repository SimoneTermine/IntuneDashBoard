# Intune Dashboard

A local desktop application for Microsoft Intune administrators.
Connects to Microsoft Graph API, caches data in a local SQLite database,
and provides a rich UI for device management, policy exploration, governance,
and security baseline auditing.

**Current version: 1.4.0**

---

## Features

| Page | Description |
|---|---|
| **Overview** | KPI cards, compliance charts, recent sync log |
| **Device Explorer** | Search, filter, sort devices; right-click context menu |
| **Policy Explorer** | Compliance, config, Settings Catalog, Endpoint Security, apps |
| **App Ops** | KPI strip, segmented state bar, App Catalog, Install Log, Error Analysis, Device Drill-down. Falls back to aggregated data when the Reports API beta endpoint is not available for the tenant |
| **Governance** | Point-in-time snapshots, drift detection between snapshots |
| **Explainability** | Full reasoning chain: why a policy applies to a device |
| **Group Usage** | Objects assigned to a group, dead-assignment detection |
| **Graph Query Lab** | Ad-hoc Graph API tool: GET with paged collection, POST/PATCH/DELETE with JSON body editor, live JSON validation, preset library |
| **Security Audit** | Baseline Audit su 12 categorie Microsoft Security Baseline, Policy Advisor con raccomandazioni per ogni gap, Security Report esportabile in CSV |
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

## Security Audit

The **Security Audit** page verifies whether your Intune tenant's cached policies cover
the key Microsoft Security Baseline categories. Run a full sync before auditing to ensure
results reflect the current state of your tenant.

### Baseline categories checked

| # | Category | Reference |
|---|---|---|
| 1 | Compliance Policies | [docs](https://learn.microsoft.com/mem/intune/protect/device-compliance-get-started) |
| 2 | Microsoft Security Baselines | [docs](https://learn.microsoft.com/windows/security/threat-protection/windows-security-configuration-framework/windows-security-baselines) |
| 3 | Microsoft Defender Antivirus | [docs](https://learn.microsoft.com/mem/intune/protect/antivirus-microsoft-defender-settings-windows) |
| 4 | Attack Surface Reduction (ASR) | [docs](https://learn.microsoft.com/windows/security/threat-protection/microsoft-defender-atp/attack-surface-reduction) |
| 5 | BitLocker Encryption | [docs](https://learn.microsoft.com/mem/intune/protect/encrypt-devices) |
| 6 | Windows Firewall | [docs](https://learn.microsoft.com/mem/intune/protect/endpoint-security-firewall-policy) |
| 7 | Device Guard / HVCI / VBS | [docs](https://learn.microsoft.com/windows/security/threat-protection/device-guard/introduction-to-device-guard-virtualization-based-security-and-windows-defender-application-control) |
| 8 | Windows Update Rings | [docs](https://learn.microsoft.com/mem/intune/protect/windows-update-for-business-configure) |
| 9 | Local Admin Password (LAPS) | [docs](https://learn.microsoft.com/windows-server/identity/laps/laps-overview) |
| 10 | Edge Browser Security | [docs](https://learn.microsoft.com/deployedge/microsoft-edge-policies) |
| 11 | TLS / Protocol Hardening | [docs](https://learn.microsoft.com/windows/security/threat-protection/windows-security-baselines) |
| 12 | User Account Control (UAC) | [docs](https://learn.microsoft.com/windows/security/identity-protection/user-account-control/user-account-control-overview) |

Each category reports one of three statuses:
- ✅ **Covered** — one or more matching policies found
- ⚠️ **Partial** — some policies found but below the recommended threshold
- ❌ **Missing** — no matching policy found

The **Policy Advisor** tab shows only actionable categories (missing/partial) with
concrete recommendations and direct links to Microsoft documentation.
The **Security Report** tab generates a full text report exportable as CSV.

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
