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
  1.2.8 -- App Ops: replaced /deviceStatuses with Reports API (getAppStatusOverviewReport)
  1.2.9 -- App Ops: getDeviceInstallStatusReport uses beta (not v1.0); UI reads
           install counts from App.raw_json[_install_overview] instead of DeviceAppStatus
  1.3.0 -- App Ops: full UI redesign (accent KPI cards, segmented state bar, empty states,
           data-source banner when Reports API beta unavailable); Install Log and Device
           Drill-down fall back to _install_overview synthetic rows when DeviceAppStatus
           is empty; Graph Query Lab: GET/POST/PATCH/DELETE selector, JSON body editor
           with live validation and Format button, Copy Result, preset library
"""

__version__ = "1.3.1"
APP_NAME = "Intune Dashboard"
