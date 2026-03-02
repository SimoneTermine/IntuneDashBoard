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

### Automatic scope re-authentication

When new Graph API permissions are added to the app (e.g. after an update),
the token cache is **automatically cleared on next startup** and you will be
prompted to sign in again with the updated permission set.
No manual action required beyond completing the sign-in flow.

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
then clear the token cache (Settings → Clear Token Cache) and re-authenticate.

**"Permission denied" when running a remediation**

The "Run on Device" action requires `DeviceManagementConfiguration.ReadWrite.All`.
Add this permission in Entra, re-grant admin consent. The app will detect the
scope change automatically on next restart and prompt for re-authentication.

**Device code dialog does not appear**

Ensure `Auth Mode` is set to `device_code` in Settings. If the token cache is
already valid, no dialog is needed. Use "Clear Token Cache" to force a new sign-in.

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

### Test Graph Connection
Clicking **Test Graph Connection** in Settings always triggers a full re-authentication:
1. The existing token cache is cleared.
2. The device code dialog appears with a URL and a short code.
3. Open the URL in any browser, enter the code, and sign in with your admin account.
4. The dialog closes automatically and the connection result is shown.

### Automatic scope upgrade
When `DEFAULT_SCOPES` changes between versions (e.g. `DeviceManagementConfiguration.ReadWrite.All`
was added in v1.1.0 for Remediations), the app detects the mismatch on startup and clears
the token cache. The next sync or Test Connection will prompt for a new sign-in that includes
the updated permissions — no manual action required.

---

## Version History

See [CHANGELOG.md](CHANGELOG.md).
