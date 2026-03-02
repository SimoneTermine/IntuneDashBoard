# Changelog

All notable changes to Intune Dashboard are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

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
