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
"""

__version__ = "1.2.6"
APP_NAME = "Intune Dashboard"
