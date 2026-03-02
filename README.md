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
| **Remediations** | Proactive Remediation scripts — list, inspect, run on-demand |
| **App Ops** | Deployment state, top failures, install error clustering |
| **Governance** | Point-in-time snapshots, drift detection between snapshots |
| **Explainability** | Full reasoning chain: why a policy applies to a device |
| **Group Usage** | Objects assigned to a group, dead-assignment detection |
| **Graph Query Lab** | Ad-hoc Graph API tool with paged collection support |
| **Settings** | Tenant / auth config, scheduler, storage paths |

---

## Requirements

- Python **3.10+**
- PySide6, msal, sqlalchemy, requests, apscheduler

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
| `DeviceManagementConfiguration.Read.All` | Policies, remediations (list/read) |
| `DeviceManagementConfiguration.ReadWrite.All` | **Run Remediation on-demand** (write) |
| `DeviceManagementApps.Read.All` | Apps, install status |
| `Group.Read.All` | Group targeting, dead-assignment detection |
| `User.Read.All` | User memberships, device–user correlation |
| `Device.Read.All` | Device group memberships |
| `DeviceManagementRBAC.Read.All` | RBAC scope tags |

3. **Grant admin consent** for your tenant.
4. **Authentication → Add a platform → Mobile and desktop applications**
   Enable redirect URI: `https://login.microsoftonline.com/common/oauth2/nativeclient`
5. **Advanced settings → Allow public client flows → Yes**

> **Note on `ReadWrite.All` vs `Read.All`**: Adding `ReadWrite.All` implicitly covers
> `Read.All` — you do not need to add both. The write permission is only exercised
> when you explicitly click "Run on Device" in the Remediations page.

---

## Quick Start

```bash
git clone https://github.com/yourorg/intune-dashboard.git
cd intune-dashboard

python -m venv .venv
.venv\Scripts\activate        # Windows
# or: source .venv/bin/activate  # macOS / Linux

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

### Authentication & Token Cache

- The app requests Graph delegated scopes at runtime from `DEFAULT_SCOPES`, including
  `DeviceManagementConfiguration.Read.All`.
- Token acquisition is **silent-first** (`acquire_token_silent`) and only falls back to
  device code flow when interaction is actually required (first sign-in, missing consent,
  expired/non-refreshable session).
- Token cache path (Windows): `%LOCALAPPDATA%\IntuneDashboard\msal_cache.bin`
  (legacy `%APPDATA%` cache is migrated automatically when found).
- Cache protection:
  - Preferred: DPAPI encrypted persistence via `msal-extensions`.
  - Fallback: local file cache with restrictive permissions best-effort.
- You can sign out from:
  - **Account → Sign out / Clear token cache** (main menu), or
  - **Settings → Sign out / Clear token cache**.
- Sign-out removes MSAL accounts, deletes local cache files, and forces a fresh
  device code login on next sync.

If new scopes are added in a future release, the app performs incremental consent:
it will prompt device code only once to request the new missing consent, then continue
to reuse silent auth on subsequent sync runs.

### Demo Mode

Enable in Settings to load synthetic data without credentials.

---

## Portal Deep-links

All "Open in Intune Portal" context menu actions use the correct portal blade per policy type.
URL construction is centralised in `app/utils/intune_links.py`.

| Policy type | Blade |
|---|---|
| Compliance policy | `CompliancePolicyOverview.ReactView` |
| Settings Catalog / Endpoint Security | `PolicySummaryBlade` |
| Windows / macOS Update config | `SoftwareUpdatesConfigurationSummaryReportBlade` |
| Classic config profile | `DeviceConfigurationMenuBlade` |
| App | `SettingsMenu/~/0` |
| Remediation script | `DeviceHealthScriptsMenuBlade/~/scriptdetails` |
| Device | `DeviceSettingsMenuBlade/~/overview` |

---

## Database Migration

The app automatically migrates existing databases on startup (`database.py/_migrate_db`):

- **`outcomes` table**: if the v1.0 schema is detected (missing `status` column),
  the table is dropped and recreated. `outcomes` is fully derived data — it is rebuilt
  from scratch on the next sync.
- **Other tables**: additive `ALTER TABLE` migrations add missing columns
  non-destructively (no data loss).

If you prefer to start fresh: delete `%APPDATA%\IntuneDashboard\intune_dashboard.db`
and restart. A full sync will repopulate everything.

---

## Troubleshooting

**Remediations page is empty after sync**

The Remediations sync requires `DeviceManagementConfiguration.Read.All`.
Verify admin consent has been granted in Entra for this permission,
then use **Sign out / Clear token cache** and re-authenticate.

**"Permission denied" when running a remediation**

The "Run on Device" action requires `DeviceManagementConfiguration.ReadWrite.All`.
Add this permission in Entra, re-grant admin consent, then sign out once and log in again.

**Device code dialog does not appear**

Ensure `Auth Mode` is set to `device_code` in Settings. If the token cache is
already valid, no dialog is needed. Use "Sign out / Clear token cache" to force a new sign-in.


**AADSTS500113: No reply address is registered**

If this appears when opening admin consent, configure a redirect URI in Entra app registration
(or use the app's built-in admin-consent URL without `redirect_uri`, available from Account menu).
For public client/device-code apps, ensure **Mobile and desktop applications** is enabled and
`https://login.microsoftonline.com/common/oauth2/nativeclient` is present.

**`no such column: outcomes.status` error**

Your database was created with v1.0. Update `app/db/database.py` to v1.1.0 —
the migration will drop and recreate `outcomes` automatically on next startup.

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
python -m pytest tests/ -v             # with pytest
```

---

## Authentication — How It Works

1. App tries `acquire_token_silent` with the full scope set.
2. If silent fails because interaction/consent is required, app starts device code flow.
3. On success, cache is persisted and reused across app restarts.
4. If admin consent is required (for example `DeviceManagementConfiguration.Read.All` missing),
   app shows a clear message and can open the tenant admin consent URL.

---

## Version History

See [CHANGELOG.md](CHANGELOG.md).
