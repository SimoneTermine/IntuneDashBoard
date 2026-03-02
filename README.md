# Intune Dashboard

A local desktop application for Microsoft Intune administrators.
Connects to Microsoft Graph API, caches data in a local SQLite database,
and provides a rich UI for device management, policy exploration, and governance.

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
- **Sign out**: Settings → 🚪 Sign out / Clear Token Cache

### Automatic scope re-authentication

When `DEFAULT_SCOPES` changes between versions, the token cache is automatically
cleared on next startup and you will be prompted to sign in once with the updated
permission set. No manual action required.

### Admin consent

If you see a 403 error or AADSTS65001, a Global Administrator must grant consent:

1. Settings → **🔑 Open Admin Consent Page**
2. Sign in as a Global Administrator and click Accept
3. Settings → Sign out / Clear Token Cache → re-sync

---

## Portal Deep-links

All "Open in Intune Portal" context menu actions use the correct portal blade.
URL construction is centralised in `app/utils/intune_links.py`.

| Policy type | Blade |
|---|---|
| Compliance policy | `CompliancePolicyOverview.ReactView` |
| Settings Catalog / Endpoint Security | `PolicySummaryBlade` |
| Windows / macOS Update config | `SoftwareUpdatesConfigurationSummaryReportBlade` |
| Classic config profile | `DeviceConfigurationMenuBlade` |
| App | `SettingsMenu/~/0` |
| Device | `DeviceSettingsMenuBlade/~/overview` |

---

## Database Migration

The app automatically migrates existing databases on startup:

- **`outcomes` table**: dropped and recreated if the v1.0 schema is detected.
- **`remediations` table**: dropped automatically on first startup after v1.2.1
  upgrade (orphaned table from the removed Remediations feature).
- **Other tables**: additive `ALTER TABLE` migrations (non-destructive).

To start fresh: delete `%APPDATA%\IntuneDashboard\intune_dashboard.db` and restart.

---

## Troubleshooting

**Device code dialog does not appear**

Ensure `Auth Mode` is set to `device_code` in Settings. If the token cache is
already valid, no dialog is needed. Use "Sign out / Clear Token Cache" to force
a new sign-in.

**`no such column: outcomes.status` error**

Your database was created with v1.0. The migration runs automatically on startup —
just restart the app.

**403 error on sync**

Verify all required permissions are granted with admin consent in Entra.
Then: Settings → Sign out / Clear Token Cache → Sync Now.

**Log files** — all logs in `%APPDATA%\IntuneDashboard\logs\`

| File | Contents |
|---|---|
| `intune_dashboard.log` | Root logger |
| `graph.log` | HTTP client — rate limiting, 401/403, retries |
| `collector.log` | Sync steps — per-item details |
| `db.log` | Database layer |

---

## Unit Tests

```bash
python tests/test_intune_links.py      # self-contained, no pytest required
python -m pytest tests/ -v
```

---

## Version History

See [CHANGELOG.md](CHANGELOG.md).
