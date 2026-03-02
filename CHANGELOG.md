# Changelog

All notable changes to Intune Dashboard are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

---

## [1.1.1] — 2026-03-02

### Fixed
- **Device code dialog missing on "Test Graph Connection"**: the button was silently
  returning a cached token without showing the sign-in prompt. Fixed by explicitly
  clearing the token cache before starting the `AuthWorker`, so the device code
  dialog always appears when the user clicks the button.
- **Remediations 403 — automatic re-authentication**: `auth.py` now compares the
  scopes present in the cached token against `DEFAULT_SCOPES`. If the cached token
  is missing a required scope (e.g. `DeviceManagementConfiguration.ReadWrite.All`
  added in v1.1.0), the cache is cleared automatically and the device code flow is
  triggered on the next sync or Test Connection — no manual "Clear Token Cache" step
  required.
- **Scope tracking first-run bug**: on the first run after replacing `auth.py`, the
  `msal_scopes.json` file did not exist yet. The previous code wrote the new scope
  hash without clearing the cache, leaving a stale token in place. Fixed: on first
  run the cache is now cleared unconditionally so a fresh consent is obtained.
- **`app/db/database.py` migration**: `outcomes` table is dropped and recreated if
  the v1.0.0 schema (`applies`, `computed_at` columns) is detected, preventing the
  `no such column: outcomes.status` error on existing databases.
- **`DriftReport` model missing**: the class was accidentally omitted from the
  delivered `models.py`, causing `ImportError` in `queries.py` and `governance_page`.

---

## [1.1.0] — 2026-03-02

### Added
- **Remediations page** — lists all Proactive Remediation scripts (deviceHealthScripts)
  with name, publisher, type (Custom / Microsoft), last-modified date, and description.
  Right-click context menu: Open in Portal, Run on Device, Copy, Export.
- **Run Remediation on Device** — dialog to pick a target device and trigger an on-demand
  run via Graph `POST .../initiateOnDemandProactiveRemediation`. Graceful error
  messages for 403 (permission), 404 (not found), and Microsoft-managed (global) scripts.
- **Centralised portal URL builder** (`app/utils/intune_links.py`) — single source of truth
  for all Intune / Entra deep-links. Pure builder functions are fully unit-testable.
- **Scope change detection** in `auth.py` — when `DEFAULT_SCOPES` changes between
  versions (e.g. a new permission is added), the MSAL token cache is cleared
  automatically on next startup and the user is prompted to re-authenticate with
  the updated permission set. No manual cache clearing required.
- **Device code dialog** restored in Settings → "Test Graph Connection":
  a modal dialog displays the URL and the sign-in code while waiting for authentication.
  The dialog closes automatically when sign-in completes.
- **Unit tests** (`tests/test_intune_links.py`) — 50 test cases for all URL builders.
  Self-contained runner: `python tests/test_intune_links.py`.
- **Credential masking** in Settings — Tenant ID and Client ID are hidden by default;
  a toggle button (👁) reveals the value.
- `app/version.py` — single source of truth for `__version__ = "1.1.0"` and `APP_NAME`.
- `DeviceManagementConfiguration.ReadWrite.All` added to `DEFAULT_SCOPES` (required
  for the Remediations "Run on Device" action).
- `GraphClient.post()` method for write operations.
- **DB migration** in `database.py` (`_migrate_db`) — automatically migrates existing
  databases on startup:
  - `outcomes` table: dropped and recreated if the v1.0 schema is detected
    (missing `status` column). Data is fully derived and rebuilt on next sync.
  - Additive `ALTER TABLE` migrations for other tables (non-destructive).

### Fixed
- **Device code dialog** was no longer appearing in Settings after the settings page
  rewrite; restored `AuthWorker`-based flow with proper modal dialog.
- **Compliance policy portal URLs** now open `CompliancePolicyOverview.ReactView`
  (`Microsoft_Intune_DeviceSettings` namespace) with numeric `platform~` enum and
  `policyType~/35`. Previously used `PolicySummaryBlade` → 404 in portal.
- **Windows/macOS Update config policy URLs** now open
  `SoftwareUpdatesConfigurationSummaryReportBlade` with correct type and journey params.
- **App portal URLs** now use `SettingsMenu/~/0` instead of `AppOverview.ReactView` (404).
- **Generic config policy fallback** uses `DeviceConfigurationMenuBlade` — never falls
  through to `PolicySummaryBlade` for unclassified config profiles.
- **`outcomes` table schema** — v1.0 schema had `applies` (bool) / `computed_at` instead
  of `status` / `source` / `error_code` / `raw_json` / `synced_at`. Fixed in `models.py`
  and automatically migrated by `database.py`.
- **`DriftReport` model** missing from delivered `models.py`; restored.

### Changed
- Window title: removed `[read-only]` — title is now `Intune Dashboard 1.1.0`.
- README fully rewritten in English with updated permissions table.
- Remediations sync step added to pipeline (after apps, before assignments).

---

## [1.0.0] — 2026-02-28

### Added
- Initial release: Device Explorer, Policy Explorer, App Ops, Governance, Explainability,
  Group Usage, Graph Query Lab, context menus, export, demo mode, per-subsystem logging.
