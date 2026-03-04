# Changelog

All notable changes to Intune Dashboard are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

---

## [1.3.1] — 2026-03-04

### Fixed
- **`Catalog refresh failed: datetime.datetime object is not subscriptable`** — `get_app_install_summary()` used `(app.last_modified_datetime or "")[:19]`; when the column is a Python `datetime` object (not a string), slicing raises `TypeError`. Fixed by using the `_fmt_dt()` helper.
- **"Open in Intune Portal" → 404 `AppOverviewBlade` error** — the blade was removed from the Intune portal. Correct URL: `SettingsMenu/~/0/appId/{id}`. Updated in `_show_ctx_menu()`.
- **App Ops UI regressed visually** — custom `KpiCard` with `paintEvent` and complex `StateBar` caused rendering issues. Reverted to global `KpiCard` from `app/ui/widgets/kpi_card.py`; simplified `StateBar` to a flat proportional strip; removed `paintEvent` border.

### Changed
- `app/analytics/app_monitoring_queries.py`: `get_app_install_summary()` uses `_fmt_dt()` for dates.
- `app/ui/pages/app_ops_page.py`: rewritten — global KpiCard, simplified StateBar, correct portal URL.
- `app/version.py`: bumped to `1.3.1`.


---

## [1.3.0] — 2026-03-04

### Added
- **App Ops — complete UI redesign**
  - `KpiCard` redesigned with colored left-accent border, separated from the
    global widget in `app/ui/widgets/kpi_card.py` to allow per-page customisation.
  - `StateBar` rewritten: proportional segments with rounded ends, inline state
    labels, per-state color coding (Catppuccin Mocha palette).
  - `InfoBanner` helper widget: `info` / `warning` / `error` levels with icon.
  - **Data-source banner**: when `DeviceAppStatus` is empty (per-device Reports API
    endpoint unavailable), a yellow `⚠️` banner appears below the state bar
    explaining the situation and confirming KPIs are still accurate.
  - **Install Log synthetic banner**: shown inside the Install Log tab when rows
    are synthesised from `_install_overview` rather than per-device records.
  - **Error Analysis empty state**: replaces empty table with a friendly icon +
    explanation when no error-code data is available.
  - **Device Drill-down empty state**: placeholder shown before an app is selected;
    replaced by drill-down data (or aggregated overview) once an app is chosen.
  - Right-click context menu fully rewritten: consistent styling, correct portal
    URL, "Show in Install Log" cross-tab action.
  - Header now shows last-refresh timestamp.

- **App Ops — Install Log and Device Drill-down fallback**
  - `get_all_install_records()`: when `DeviceAppStatus` is empty, calls new
    `_get_install_records_from_overview()` helper that synthesises one row per
    non-zero state bucket from `App.raw_json["_install_overview"]`.
    Synthetic rows carry `"_synthetic": True` so the UI renders the banner.
  - `get_device_installs_for_app()`: same fallback via
    `_get_device_overview_for_app()`. The drill-down tab shows aggregated counts
    (e.g. "3 devices — installed") rather than an empty table.
  - State filter in Install Log now correctly filters synthetic rows too.

- **Graph Query Lab — POST / PATCH / DELETE support**
  - Method selector: `GET`, `POST`, `PATCH`, `DELETE`.
  - **Request Body editor** (JSON): appears automatically for `POST` / `PATCH`.
    Monospaced font, full height, placeholder with example body.
  - **Live JSON validation**: status indicator updates on every keystroke —
    `✓ valid JSON` (green) or `✗ <error> (line N)` (red).
  - **Format JSON** button: pretty-prints and validates the body in place.
  - **Copy Result** button: copies the full JSON output to clipboard.
  - **Preset library**: 7 built-in presets covering the most common endpoints,
    including `getAppStatusOverviewReport` and `getDeviceInstallStatusReport`
    with pre-filled example bodies.
  - Paged-collection mode automatically disabled for non-GET methods.
  - Run button accent color changes per method (green=GET, blue=POST,
    yellow=PATCH, red=DELETE).

### Changed
- `app/analytics/app_monitoring_queries.py`: `get_all_install_records()` and
  `get_device_installs_for_app()` now return `_synthetic` and `_source` metadata
  fields; both functions fall back to overview-derived rows when `DeviceAppStatus`
  is empty. `get_install_state_distribution()` returns a list of
  `{"state", "count"}` dicts (consistent with StateBar input format).
- `app/ui/pages/app_ops_page.py`: full rewrite — new KpiCard, StateBar,
  InfoBanner, empty states; context menus via unified `_build_context_menu_actions`
  helper; cross-tab "Show in Install Log" action wired from App Catalog.
- `app/ui/pages/graph_query_page.py`: full rewrite — method selector, body
  editor, preset library, Copy Result, per-method run-button styling.
- `app/version.py`: bumped to `1.3.0`.
- `README.md`: updated version badge, feature table (App Ops and Graph Query Lab
  descriptions), added "App Ops — Data Sources" and "Graph Query Lab" sections,
  corrected repo URL.

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
