# 🛡️ Intune Dashboard

A professional desktop app for Microsoft Intune administrators.
Runs **100% locally on Windows 10/11** — no backend server, no SaaS.
It connects to Microsoft Intune through Microsoft Graph API, stores data in a local SQLite database,
and provides dashboards, explainability, drift detection, and audit exports.

---

## ✨ Features

| Category | Features |
|---|---|
| **Overview** | KPI cards, compliance chart, OS breakdown, sync logs |
| **Device Explorer** | OS/compliance/ownership filters, search by device name/serial/UPN |
| **Device Detail** | Summary, per-policy compliance, app status, Entra group memberships, raw JSON, PDF |
| **Policy Explorer** | Compliance + configuration + endpoint security + assignments |
| **Group Usage** | All Intune objects assigned to a group, dead-assignment detection |
| **Explain State** | Why a device is non-compliant: reason codes, conflict heuristics |
| **App Ops** | Top failures, app error clustering |
| **Graph Query Lab** | Run custom Graph queries (v1.0/beta), single or paged mode, JSON output |
| **Governance** | Snapshots, drift comparison (added/removed/modified), blast radius |
| **Export** | CSV + JSON table export, PDF evidence pack with SHA256 |
| **Settings** | Tenant/auth configuration, connection test, scheduler, privacy options |
| **Demo Mode** | Synthetic data to explore the full UI without credentials |

### New UX capabilities
- Right-click context menu on filterable tables:
  - **Copy Cell**
  - **Copy Row JSON**
  - **Explain Selected Row** (signal hook for page-level workflows)

---

## 📋 Prerequisites

- **Windows 10 / 11** (64-bit)
- **Python 3.11+** — from [python.org](https://www.python.org/downloads/) (enable “Add to PATH”)
- **Microsoft Intune** subscription with at least **Intune Read-Only Operator** role
- **App registration in Microsoft Entra ID** (see below)

---

## 🔑 Entra App Registration

### Option A — Automatic (PowerShell)

```powershell
# Run from repository root
.\setup_app_registration.ps1 -TenantId "your-tenant-id"
```

The script creates the app registration, adds required permissions, and prints Tenant ID / Client ID.
> ⚠️ You must still grant admin consent manually in Azure portal.

### Option B — Manual (Azure portal)

1. **Azure Portal → Entra ID → App registrations → New registration**
2. Name: `Intune Dashboard (Local)` · Account type: **Single tenant**
3. After creation: **API permissions → Add permission → Microsoft Graph → Delegated**

Add only these delegated permissions:

| Permission | Why |
|---|---|
| `DeviceManagementManagedDevices.Read.All` | Read devices and per-device compliance states |
| `DeviceManagementConfiguration.Read.All` | Read configuration policies |
| `DeviceManagementApps.Read.All` | Read apps and install status |
| `Group.Read.All` | Read Entra group metadata |
| `User.Read.All` | Read users + memberships via `transitiveMemberOf` |
| `Organization.Read.All` | Tenant info for connection checks |
| `DeviceManagementRBAC.Read.All` | RBAC visibility (optional) |

> ✅ Recommended: add `Device.Read.All` (delegated) if your tenant commonly targets **device groups**.
> This enables correct membership resolution using `GET /devices/{azureADDeviceId}/transitiveMemberOf`.

4. Click **Grant admin consent for <tenant>**
5. **Authentication → Add platform → Mobile and desktop applications**
   Enable: `https://login.microsoftonline.com/common/oauth2/nativeclient`
6. **Advanced settings → Allow public client flows = YES**

---

## 🚀 Setup and Run (development)

```bash
# 1) Clone
git clone https://github.com/yourorg/intune-dashboard.git
cd intune-dashboard

# 2) Create virtual environment
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate   # Linux/macOS

# 3) Install dependencies
pip install -r requirements.txt

# 4) Run
python main.py
```

### First-time configuration

1. Open **Settings → Tenant / Auth**
2. Enter **Tenant ID** and **Client ID**
3. Set auth mode to `device_code` (recommended)
4. Click **Save Settings**
5. Click **Test Graph Connection** (you’ll receive URL + code)
6. Open the URL in browser, enter code, sign in
7. Return to app and confirm connection
8. Click **Sync Now** from sidebar

### Demo mode (no credentials required)

1. Settings → check **Enable Demo Mode**
2. **Save Settings** → **Sync Now**
3. App loads synthetic data so you can explore all pages

---

## 📁 Repository Structure

```
intune-dashboard/
├── main.py
├── requirements.txt
├── intune_dashboard.spec
├── setup_app_registration.ps1
│
├── app/
│   ├── config.py
│   ├── logging_config.py
│   ├── db/
│   ├── graph/
│   ├── collector/
│   ├── analytics/
│   ├── export/
│   ├── demo/
│   └── ui/
│       ├── main_window.py
│       ├── workers/
│       ├── widgets/
│       └── pages/
│           ├── overview_page.py
│           ├── device_explorer_page.py
│           ├── device_detail_page.py
│           ├── policy_explorer_page.py
│           ├── group_usage_page.py
│           ├── explainability_page.py
│           ├── app_ops_page.py
│           ├── graph_query_page.py
│           ├── governance_page.py
│           └── settings_page.py
│
└── tests/
```

---

## 🔄 Sync Pipeline

Sync execution order:

| Step | Graph Endpoint | Notes |
|---|---|---|
| `devices` | `deviceManagement/managedDevices` | v1.0 |
| `compliance_policies` | `deviceManagement/deviceCompliancePolicies` | v1.0 |
| `config_policies` | `deviceManagement/deviceConfigurations` + `configurationPolicies` | v1.0 + beta |
| `apps` | `deviceAppManagement/mobileApps` | v1.0 |
| `groups` | `groups` | v1.0 |
| `memberships` | `devices/{id}/transitiveMemberOf` + `users/{id}/transitiveMemberOf` | v1.0 |
| `compliance_status` | `managedDevices/{id}/deviceCompliancePolicyStates` | v1.0 |
| `assignments` | assignments per control | v1.0 |

### Sync frequency

- Default: every **60 minutes** (configurable in Settings; minimum 5 minutes)
- Manual: sidebar **↻ Sync Now**
- Cooldown: **90 seconds** between manual sync operations

---

## 🔐 Security

### Token cache
- Path: `%APPDATA%\IntuneDashboard\msal_cache.bin`
- Format: MSAL serialized token cache
- Optional hardening:

```powershell
icacls msal_cache.bin /inheritance:r /grant:r "%USERNAME%:(R,W)"
```

### What the app does **not** do
- No telemetry collection
- No data exfiltration to third-party services
- No Intune writes in current release (read-only operations)

---

## 🛠️ Troubleshooting

| Error | Fix |
|---|---|
| `401 Unauthorized` | Token expired → click **Test Graph Connection** |
| `403 Forbidden` | Missing permissions/admin consent |
| `429 Too Many Requests` | Wait and retry (built-in backoff handles most cases) |
| Empty memberships | Verify `User.Read.All` and (recommended) `Device.Read.All` |

---

## 📄 License

This project is intended as an internal/admin tooling baseline. Add your preferred license before public distribution.
