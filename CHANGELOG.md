# Changelog

All notable changes to Intune Dashboard are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

---

## [1.2.6] -- 2026-03-03

### Fixed
- **Device code prompt not appearing during Sync Now** -- When the cached
  token was expired or missing required scopes, `SyncEngine` initiated a
  device code flow but had no callback, so the flow ran silently and the sync
  stalled waiting for a sign-in that could never happen.

  Fix (three files):
  - `app/ui/workers/sync_worker.py`: `SyncWorker` gains a `device_code_ready`
    signal (user_code, verification_uri). The `run()` method passes an
    `on_device_code` callback to `SyncEngine.run_sync()`.
  - `app/collector/sync_engine.py`: `run_sync()` gains a
    `device_code_callback` parameter. The client is now authenticated
    explicitly at the very start of every sync (before any API call) so
    the sign-in dialog appears up front rather than mid-sync.
  - `app/ui/main_window.py`: `run_sync()` connects `device_code_ready` to
    a new `_on_sync_device_code()` / `_show_device_code_dialog()` method
    that renders the same sign-in dialog used by Settings -> Test Graph
    Connection (see `main_window_PATCH.py` for the exact replacement).

- **`diagnose_apps.py` stuck waiting with no prompt** -- The script called
  `client.authenticate()` without a callback, so the device code was never
  printed. Fixed: a `device_code_prompt()` callback now prints the URL and
  code clearly to the console.

### Added
- `app/ui/main_window.py`: `_show_device_code_dialog()` method (reusable
  sign-in dialog extracted from settings_page logic).

### Notes
- **App Ops status counters still 0**: confirmed by `app_ops.log` that Graph
  returns HTTP 400 on `/deviceStatuses` and `/deviceInstallStates` for all 7
  apps. This is a tenant data state issue, not a code bug: the apps were
  recently deployed and the 3 enrolled devices have not yet checked in with
  install status. Run `python diagnose_apps.py` after devices check in to
  confirm data starts flowing. No code change needed.

---

## [1.2.5] — 2026-03-03

### Fixed
- **Only 3 apps visible — root cause confirmed**: The fix in v1.2.4 (removing
  `$select`) was necessary but not sufficient. The **v1.0** `/mobileApps`
  endpoint silently drops `winGetApp`, `officeSuiteApp`, and other modern app
  types in some tenant configurations regardless of `$select` usage.
  `sync_apps()` now calls `get_paged(MOBILE_APPS, api_version="beta")` which
  returns the full polymorphic collection in all tenant configurations.
- **Verbose per-app logging**: every app returned by Graph is now logged at
  INFO level with its OData type and display name before upsert, so any
  missing types are immediately visible in `app_ops.log` without DEBUG mode.

### Added
- **`diagnose_apps.py`** — standalone diagnostic script (run from repo root).
  Authenticates using the same device-code flow as the main app and:
  - Queries `/mobileApps` with both v1.0 and beta, printing type counts for
    each so the v1.0 vs beta difference is directly observable.
  - Probes `/deviceStatuses` and `/deviceInstallStates` for every app and
    prints the HTTP result and first record (if any), confirming whether
    Graph has install tracking data for the tenant.
  - Verifies token identity via the `/me` endpoint.

### Notes
- If `diagnose_apps.py` shows HTTP 400 on all install-status endpoints for all
  apps, Graph genuinely has no per-device tracking data yet. This occurs when:
  (a) apps were recently deployed and devices haven't checked in since, or
  (b) the tenant's Graph API doesn't expose install tracking for these app types
      (known limitation for certain app types like `windowsMicrosoftEdgeApp`).
  In this case the App Ops status counters will remain at 0 until devices
  check in and Graph populates the tracking data.

---

## [1.2.4] — 2026-03-03

### Fixed
- **App Ops — only win32 apps visible after sync ("Apps synced: 3" with 7 apps in
  tenant)** — root cause: `$select` on the polymorphic `/deviceAppManagement/mobileApps`
  collection caused Graph to silently drop app types whose OData derived schema does
  not declare all requested fields. `winGetApp`, `officeSuiteApp`, and other types
  were excluded while `win32LobApp` (which declares `publisher`, `description`, etc.)
  continued to appear. Fix: `$select` is no longer sent for the `mobileApps` request.
  `APP_SELECT_FIELDS` in `endpoints.py` is now `None`; `sync_apps()` calls
  `get_paged(MOBILE_APPS)` with no params so all fields and all app types are returned.
- **win32LobApp → 400 on `/deviceInstallStates`** — some tenants return
  `"Resource not found for the segment 'deviceInstallStates'"` for win32 apps
  despite the type being `win32LobApp` (known Graph behavioural inconsistency).
  `_sync_win32_statuses()` now automatically falls back to `/deviceStatuses`
  when a 400 is received, instead of logging a WARNING and giving up.
- **`windowsMicrosoftEdgeApp` 400 on `/deviceStatuses`** — downgraded from WARNING
  to DEBUG. Edge is a system-managed app type that does not expose per-device
  install status; the 400 is expected and informational.

### Changed
- `APP_SELECT_FIELDS` in `app/graph/endpoints.py` set to `None` with a detailed
  comment explaining why `$select` must not be used for the mobileApps collection.

---

## [1.2.3] — 2026-03-03

### Fixed
- **App Ops — all status counters still 0 after sync** — root cause identified:
  `PRAGMA foreign_keys=ON` is active in `database.py`. When `_sync_device_statuses`
  / `_sync_win32_statuses` used a **single shared session** for the entire app batch,
  a single `IntegrityError` (FK violation — `deviceId` not yet in `devices` table)
  rolled back the whole batch, leaving `DeviceAppStatus` empty.
  Fixed by moving each record write into its own `session_scope` transaction in
  `_save_device_app_status()` — FK failures on individual devices no longer affect
  the rest of the batch.
- **`windowsMicrosoftEdgeApp`** was missing from `DEVICE_STATUS_SUPPORTED_TYPES`
  and therefore silently skipped during install-status sync. Added along with
  `windowsMicrosoftEdgeAppChannel`, `win32CatalogApp`, and `windowsWebApp`.
- **Install-status errors logged at DEBUG** — meaningful failures (non-400/404
  Graph errors, DB write errors) were invisible at default INFO level. Upgraded
  to WARNING so they appear in `collector.log` / `app_ops.log` without requiring
  DEBUG mode.
- **Drill-down and Install Log filter returned empty** — downstream symptom of
  the empty `DeviceAppStatus` table. With the FK-transaction fix above, both
  features now work correctly once a sync completes.

### Added
- **`app_ops.log`** — dedicated log file at
  `%APPDATA%\IntuneDashboard\logs\app_ops.log`.
  Receives entries from three sources:
  - `app.ui.pages.app_ops` — KPI refresh, catalog load, drill-down navigation,
    install log filter, error analysis
  - `app.analytics.app_monitoring_queries` — SQL query results and record counts
    for every App Ops data fetch (KPIs, install log, drill-down)
  - `app.collector.apps` — per-app sync stats (records saved/skipped) and
    per-record DB errors
  Follows the same SCCM-style 2 MB rotation as all other logs.

---

## [1.2.2] — 2026-03-03

### Fixed
- **`GraphClient.test_connection()` AttributeError** — method was not reachable
  at runtime after auth. Rewrote `client.py` to guarantee the method is always
  present; `AdminConsentRequiredError` is now re-raised instead of silently caught
  so the Settings page can surface the consent button correctly.
- **App Ops — all status counters showed 0** — `get_app_monitoring_kpis()` and
  `get_app_install_summary()` used exact-case SQL equality (`== "installed"`).
  Microsoft Graph returns `"success"` for WinGet app installs and may vary
  capitalisation across app types. All state comparisons are now
  case-insensitive (`func.lower().in_()`) and include canonical variant spellings:
  - `"success"` → counted as *installed*
  - `"installfailed"` / `"uninstallFailed"` → counted as *failed*
  - `"pending"` / `"downloading"` / `"installing"` → counted as *pending*
  - `"notApplicable"` / `"excluded"` → counted as *not installed*
- **`get_install_state_distribution()`** normalises variant state names before
  building the overview bar, so colours map consistently.
- **`get_app_error_analysis()`** now uses the same case-insensitive failed-state
  filter as the KPI query.

### Changed
- **Log rotation rewritten** (`app/logging_config.py`). Replaced
  `RotatingFileHandler` (`.log.1 / .log.2` style) with a new
  `SccmRotatingFileHandler` that mirrors SCCM/ConfigMgr behaviour:
  - Threshold: **2 MB** per file (down from 10 MB).
  - On rotation: active log is renamed  `<name>_<YYYY-MM-DD>.log`.
  - Collision handling: appends `_1`, `_2`, … when today's archive already exists.
  - Fresh `<name>.log` is opened immediately after rename.
  - On-disk format: `intune_dashboard_2026-03-03.log`,
    `intune_dashboard_2026-03-03_1.log`, …

---

## [1.2.1] — 2026-03-03

### Removed
- **Proactive Remediations feature** removed entirely pending redesign.
  Deleted files: `app/collector/remediations.py`, `app/ui/pages/remediations_page.py`.
  Removed from: sidebar nav, `__init__.py`, sync pipeline, `Remediation` DB model,
  endpoint constants, `remediation_url()` / `open_remediation_portal()` helpers.
- **`DeviceManagementConfiguration` scopes** (`Read.All`, `ReadWrite.All`) removed
  from `DEFAULT_SCOPES` — no longer required without the Remediations feature.

### Changed
- `database.py` migration now drops the orphaned `remediations` table automatically
  on first startup after upgrade (no manual action needed).

---

## [1.2.0] — 2026-03-02

### Added
- **DPAPI-encrypted token cache** via msal-extensions (Windows). Cache stored at
  `%APPDATA%\IntuneDashboard\msal_cache.bin` — encrypted and bound to the Windows
  user account. Falls back to plain SerializableTokenCache if msal-extensions is
  not installed.
- **Sign out / Clear Token Cache** button renamed and improved. `sign_out()` now
  removes MSAL accounts, deletes cache files, and resets the singleton.
- **Copy Code button** in device code dialog — copies the sign-in code to the
  clipboard with one click.
- **Admin Consent URL** helper (`admin_consent_url()`, `open_admin_consent_page()`)
  and corresponding button in Settings.
- **`AdminConsentRequiredError`** exception raised on AADSTS65001 / consent_required
  errors, with a clear message directing the admin to grant consent.
- **`cache_type()`** method on `MSALAuth` returns `'DPAPI'` or `'plain'`; shown in
  Test Connection result.

### Fixed
- **Repeated device code flow** on ReadWrite.All vs Read.All scope split.
  `_has_required_scopes()` now treats a granted `ReadWrite.All` as satisfying a
  `Read.All` requirement, preventing unnecessary re-authentication.
- **Legacy plain-text cache migration** — if DPAPI is available and the existing
  cache file is plain JSON, it is deleted and the user re-authenticates once with
  the encrypted store.

---

## [1.1.1] — 2026-03-02

### Fixed
- **Device code dialog missing on "Test Graph Connection"**: the button was silently
  returning a cached token without showing the sign-in prompt.
- **Scope tracking first-run bug**: `msal_scopes.json` not present on first run
  caused the cache to remain stale instead of being cleared.
- **`app/db/database.py` migration**: `outcomes` table is dropped and recreated if
  the v1.0.0 schema is detected (missing `status` column).
- **`DriftReport` model missing** from `models.py`; restored.

---

## [1.1.0] — 2026-03-02

### Added
- **Centralised portal URL builder** (`app/utils/intune_links.py`).
- **Scope change detection** in `auth.py`.
- **Device code dialog** in Settings → Test Graph Connection.
- **Unit tests** (`tests/test_intune_links.py`) — 50 test cases.
- **Credential masking** in Settings (👁 toggle).
- `app/version.py` — single source of truth for version and app name.
- `GraphClient.post()` method for write operations.
- **DB migration** in `database.py` (`_migrate_db`).

### Fixed
- Compliance policy portal URLs.
- Windows/macOS Update config policy URLs.
- App portal URLs (`SettingsMenu/~/0`).
- Generic config policy fallback (`DeviceConfigurationMenuBlade`).

### Changed
- Window title updated to include version.
- README rewritten in English.

---

## [1.0.0] — 2026-02-28

### Added
- Initial release: Device Explorer, Policy Explorer, App Ops, Governance,
  Explainability, Group Usage, Graph Query Lab, context menus, export,
  demo mode, per-subsystem logging.
