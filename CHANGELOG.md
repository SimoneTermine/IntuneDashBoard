# Changelog

All notable changes to Intune Dashboard are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

---

## [1.2.9] — 2026-03-03

### Fixed
- **App Ops — install counters still 0 in the UI despite overview data arriving**
  — two root causes identified from `app_ops.log`:

  1. **`getDeviceInstallStatusReport` called with `api_version="v1.0"`** — the
     endpoint is beta-only for this tenant; v1.0 returned HTTP 400
     `"Resource not found for the segment 'getDeviceInstallStatusReport'"`.
     Fix: changed to `api_version="beta"` in `_fetch_device_install_status()`.

  2. **`get_app_install_summary()` and `get_app_monitoring_kpis()` read only from
     `DeviceAppStatus`** — the table remains empty until `getDeviceInstallStatusReport`
     succeeds, even though `getAppStatusOverviewReport` (always working) stores
     accurate counts in `App.raw_json["_install_overview"]` after every sync.
     Fix: `get_app_install_summary()` now reads `_install_overview` from
     `App.raw_json` as primary source; `get_app_monitoring_kpis()` sums all apps'
     overview counts for KPI cards. `DeviceAppStatus` is kept as fallback for
     demo mode and backwards compatibility.

### Changed
- `app/analytics/app_monitoring_queries.py`: `get_app_install_summary()` and
  `get_app_monitoring_kpis()` use `App.raw_json["_install_overview"]` as primary
  source. `get_install_state_distribution()` uses the same overview when available.
- `app/collector/apps.py`: `_fetch_device_install_status()` uses `api_version="beta"`.

---

## [1.2.8] — 2026-03-03

### Fixed
- **App Ops — all install status endpoints returning HTTP 400** — root cause:
  the `/mobileApps/{id}/deviceStatuses` and `/mobileApps/{id}/deviceInstallStates`
  navigation properties were removed from the Graph API `mobileApp` base class
  in May 2023 (MC531735). They return `"Resource not found for the segment"`
  for every app type, regardless of OData type cast.

  Fix: replaced both endpoints with the official Intune Reports API:
  - `POST /beta/deviceManagement/reports/getAppStatusOverviewReport`
    (KPI aggregates: Installed, Failed, Pending, NotInstalled, NotApplicable)
  - `POST /beta/deviceManagement/reports/getDeviceInstallStatusReport`
    (per-device rows: DeviceId, DeviceName, InstallState, ErrorCode, …)

  Aggregated counts stored in `App.raw_json["_install_overview"]` for UI use.
  Per-device rows stored in `DeviceAppStatus` for drill-down and install log.

  Ref: https://techcommunity.microsoft.com/blog/intunecustomersuccess/
  support-tip-retrieving-intune-apps-reporting-data-from-microsoft-graph-beta-api

### Changed
- `app/graph/endpoints.py`: removed `APP_DEVICE_STATUSES` / `APP_WIN32_INSTALL_STATES`;
  added `APP_STATUS_OVERVIEW_REPORT` and `APP_DEVICE_INSTALL_STATUS_REPORT`.
- `app/collector/apps.py`: full rewrite of install-status methods to use Reports API.
- `diagnose_apps.py`: updated to test both Reports API endpoints.

---

## [1.2.7] — 2026-03-03

### Fixed
- **App Ops install status counters still 0 — root cause confirmed**: `$select` on
  `/deviceStatuses` and `/deviceInstallStates` caused HTTP 400 for all app types
  (polymorphic sub-resources). Removed `$select` from both calls.
- **400 errors logged without actual Graph message**: now logs `e.raw` so the real
  `errorCode` and `message` from Graph are visible in `app_ops.log`.

---

## [1.2.6] — 2026-03-03

### Fixed
- **Device code prompt not appearing during Sync Now** — `SyncWorker` now emits a
  `device_code_ready` signal; `SyncEngine.run_sync()` authenticates explicitly at
  the start; `MainWindow.run_sync()` shows the same sign-in dialog as Settings.
- **`diagnose_apps.py` stuck waiting** — added console `device_code_prompt()` callback.

---

## [1.2.5] — 2026-03-03

### Fixed
- **Apps synced: 3 instead of 7** — v1.0 API silently excludes `winGetApp`,
  `officeSuiteApp`, `windowsMicrosoftEdgeApp` in this tenant. Switched to beta API.

### Added
- `diagnose_apps.py` standalone diagnostic tool (v1.0 vs beta comparison).
- Verbose per-app type logging at INFO level.

---

## [1.2.4] — 2026-03-03

### Fixed
- **Only win32 apps visible** — `$select` on polymorphic `mobileApps` collection
  silently dropped non-win32 types. `APP_SELECT_FIELDS` set to `None`.
- **win32LobApp 400 on `/deviceInstallStates`** — automatic fallback to `/deviceStatuses`.

---

## [1.2.3] — 2026-03-03

### Fixed
- **All status counters 0** — FK constraint + shared session caused entire batch
  rollback on first FK violation. Per-record `session_scope` transactions.
- `windowsMicrosoftEdgeApp` missing from `DEVICE_STATUS_SUPPORTED_TYPES`.
- Meaningful errors upgraded from DEBUG to WARNING.

### Added
- `app_ops.log` dedicated subsystem log (SCCM-style 2 MB rotation).

---

## [1.2.2] — 2026-03-03

### Fixed
- `GraphClient.test_connection()` AttributeError at runtime.
- App Ops counters 0 due to exact-case state comparisons; now case-insensitive
  with Graph variant spelling support (`"success"` → installed, etc.).

### Changed
- Log rotation: `SccmRotatingFileHandler` (2 MB threshold, date-stamped archives).

---

## [1.2.1] — 2026-03-03

### Removed
- Proactive Remediations feature and `DeviceManagementConfiguration` scopes.

---

## [1.2.0] — 2026-03-02

### Added
- DPAPI-encrypted token cache, Sign out UI, Copy Code button, Admin Consent URL.
- `AdminConsentRequiredError` on AADSTS65001.

### Fixed
- Repeated device code on ReadWrite.All vs Read.All scope split.
- Legacy plain-text cache migration to DPAPI.

---

## [1.1.1] — 2026-03-02

### Fixed
- Device code dialog missing on "Test Graph Connection".
- Scope tracking first-run bug.
- `outcomes` / `device_app_statuses` DB migration.

---

## [1.1.0] — 2026-03-02

### Added
- Centralised portal URL builder, scope change detection, device code dialog,
  unit tests, credential masking, `app/version.py`, `GraphClient.post()`, DB migration.

---

## [1.0.0] — 2026-02-28

### Added
- Initial release: Device Explorer, Policy Explorer, App Ops, Governance,
  Explainability, Group Usage, Graph Query Lab, context menus, export, demo mode.
