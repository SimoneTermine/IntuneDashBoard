"""
app/version.py -- Single source of truth for the application version.
  1.0.0 -- initial release
  1.1.0 -- Policy Explorer, App Ops, Governance, Group Usage, context menus
  1.1.1 -- Device code dialog fix, scope tracking, DB migration fixes
  1.2.0 -- DPAPI token cache, Sign out UI, Copy Code button, admin consent URL
  1.2.1 -- Removed Proactive Remediations feature and all related permissions
  1.2.2 -- GraphClient.test_connection fix, SCCM-style log rotation (2 MB)
  1.2.3 -- App Ops: per-record FK-safe transactions, app_ops.log subsystem
  1.2.4 -- App Ops: $select removed from mobileApps, win32 400 fallback
  1.2.5 -- App Ops: mobileApps synced via beta API, verbose type logging
  1.2.6 -- Sync: device code dialog shown during Sync Now when token expires
  1.2.7 -- App Ops: $select removed from /deviceStatuses and /deviceInstallStates
  1.2.8 -- App Ops: replaced /deviceStatuses with Reports API
  1.2.9 -- App Ops: getDeviceInstallStatusReport uses beta; UI reads from App.raw_json
  1.3.0 -- App Ops: full UI redesign; Graph Query Lab: GET/POST/PATCH/DELETE
  1.3.1 -- App Ops: KpiCard revert, portal URL fix, datetime slice fix
  1.4.0 -- Security Hardening Hub: Baseline Audit (12 categorie), Policy Advisor,
           Security Report con export CSV. Nuova sezione SECURITY in sidebar.
           Nuovi file: app/analytics/security_baseline.py,
           app/ui/pages/security_page.py
  1.4.1 -- Security Audit: pannello dettaglio Baseline Audit resizable via QSplitter
"""

__version__ = "1.4.1"
APP_NAME = "Intune Dashboard"
