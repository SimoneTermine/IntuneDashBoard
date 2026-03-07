# Changelog

All notable changes to Intune Dashboard are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

---

## [1.4.1] — 2026-03-05

### Changed
- `app/ui/pages/security_page.py`: tab Baseline Audit — tabella e pannello
  dettaglio ora separati da un `QSplitter` verticale trascinabile. Il pannello
  dettaglio non ha più altezza fissa (`setMaximumHeight(140)` rimosso);
  proporzione iniziale 65% tabella / 35% dettaglio, ridimensionabile a piacere.
- `app/version.py`: bumped a `1.4.1`.
- `CHANGELOG.md`: aggiornato.

---

## [1.4.0] — 2026-03-04

### Added
- **Security Hardening Hub** — nuova sezione `SECURITY` nella sidebar con la
  pagina `SecurityPage` (`app/ui/pages/security_page.py`).

- **Baseline Audit tab**
  - Engine `app/analytics/security_baseline.py` con 12 `BaselineCategory`
    allineate ai Microsoft Security Baseline:
    Compliance Policies, Microsoft Security Baselines, Defender Antivirus,
    Attack Surface Reduction, BitLocker, Windows Firewall, Device Guard/VBS/HVCI,
    Windows Update Rings, LAPS, Edge Browser, TLS/Protocol Hardening, UAC.
  - Audit eseguito in background (`QThread`) per non bloccare la UI.
  - Ogni categoria restituisce `status`: `covered | partial | missing`.
  - Tabella con colonne: Categoria, Status, Policy trovate, Platform, Tipo.
  - Pannello dettaglio sotto la tabella: policy abbinate e raccomandazione.

- **Policy Advisor tab**
  - Mostra solo categorie `missing` o `partial`, ordinate per priorità.
  - `_CategoryCard` con bordo colorato (rosso = missing, giallo = partial),
    descrizione, raccomandazione in evidenza, link alla documentazione Microsoft
    e lista delle policy parzialmente abbinate.

- **Security Report tab**
  - Riepilogo testuale strutturato: Security Score %, conteggi per stato,
    dettaglio per categoria, sezione "Prossimi Passi".
  - Export CSV (`security_audit_YYYYMMDD_HHMMSS.csv`).
  - Pulsante "Copia Report" per clipboard.

- **KPI cards**: Security Score % con colore adattivo (verde ≥75%, giallo ≥40%,
  rosso <40%), Coperti, Parziali, Mancanti.

- **Sidebar**: aggiunta sezione `SECURITY` tra `GOVERNANCE` e `SETTINGS`
  con voce `🛡️ Security Audit`.

### Changed
- `app/ui/pages/__init__.py`: aggiunto export `SecurityPage`.
- `app/ui/main_window.py`: aggiunto import `SecurityPage`; nuova sezione
  `SECURITY` in `nav_entries`; nuova entry `"security"` in `self._pages`.
- `app/version.py`: bumped a `1.4.0`.
- `README.md`: aggiornata versione e feature table.

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
    `✓ valid JSON` (green) or `✗ <e> (line N)` (red).
  - **Format JSON** button: pretty-prints and validates the body in place.
  - **Copy Result** button: copies the full JSON output to clipboard.
  - **Preset library**: 7 built-in presets covering the most common endpoints.
  - Paged-collection mode automatically disabled for non-GET methods.
  - Run button accent color changes per method (green=GET, blue=POST,
    yellow=PATCH, red=DELETE).

### Changed
- `app/analytics/app_monitoring_queries.py`: updated fallback logic.
- `app/ui/pages/app_ops_page.py`: full rewrite.
- `app/ui/pages/graph_query_page.py`: full rewrite.
- `app/version.py`: bumped to `1.3.0`.
- `README.md`: updated version badge and feature table.

---

## [1.2.9] — 2026-03-03

### Fixed
- **App Ops — install counters still 0** — two root causes:
  1. `getDeviceInstallStatusReport` called with `api_version="v1.0"` — fixed to `beta`.
  2. `get_app_install_summary()` read only from `DeviceAppStatus` — now uses
     `App.raw_json["_install_overview"]` as primary source.

### Changed
- `app/analytics/app_monitoring_queries.py`: primary source switched.
- `app/collector/apps.py`: `api_version="beta"` for device install status.

---

## [1.2.8] — 2026-03-03

### Fixed
- **App Ops — all install status endpoints returning HTTP 400** — replaced deprecated
  `/deviceStatuses` and `/deviceInstallStates` with the Intune Reports API:
  `getAppStatusOverviewReport` and `getDeviceInstallStatusReport`.

---

## [1.2.7] — 2026-03-03

### Fixed
- App Ops: `$select` removed from `/deviceStatuses` and `/deviceInstallStates`.

---

## [1.2.6] — 2026-03-03

### Fixed
- Sync: device code dialog shown during Sync Now when token expires.

---

## [1.2.5] — 2026-03-03

### Changed
- App Ops: mobileApps synced via beta API, verbose type logging.

---

## [1.2.4] — 2026-03-03

### Fixed
- App Ops: `$select` removed from mobileApps (polymorphic collection).
- win32LobApp 400 on `/deviceInstallStates` — automatic fallback.

---

## [1.2.3] — 2026-03-03

### Fixed
- All status counters 0 — FK constraint + shared session issue. Per-record `session_scope`.
- `windowsMicrosoftEdgeApp` missing from `DEVICE_STATUS_SUPPORTED_TYPES`.

### Added
- `app_ops.log` dedicated subsystem log (SCCM-style 2 MB rotation).

---

## [1.2.2] — 2026-03-03

### Fixed
- `GraphClient.test_connection()` AttributeError at runtime.
- App Ops counters 0 due to case-sensitive state comparisons.

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

---

## [1.1.1] — 2026-03-02

### Fixed
- Device code dialog missing on "Test Graph Connection".
- Scope tracking first-run bug.

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
