"""
app/graph/endpoints.py

Graph API endpoint definitions.
All $select field lists have been verified against the microsoft.graph schema.

v1.2.1: Removed DEVICE_HEALTH_SCRIPTS, DEVICE_REMEDIATION_RUN,
        REMEDIATION_SELECT_FIELDS (Proactive Remediations feature removed).
v1.2.4: APP_SELECT_FIELDS set to None — see below for rationale.
"""

# ── Devices ────────────────────────────────────────────────────────────────
MANAGED_DEVICES          = "deviceManagement/managedDevices"
MANAGED_DEVICE_BY_ID     = "deviceManagement/managedDevices/{device_id}"

# ── Compliance policies ────────────────────────────────────────────────────
DEVICE_COMPLIANCE_POLICIES      = "deviceManagement/deviceCompliancePolicies"
DEVICE_COMPLIANCE_POLICY_BY_ID  = "deviceManagement/deviceCompliancePolicies/{policy_id}"
DEVICE_COMPLIANCE_ASSIGNMENTS   = "deviceManagement/deviceCompliancePolicies/{policy_id}/assignments"
DEVICE_COMPLIANCE_DEVICE_STATUS = "deviceManagement/deviceCompliancePolicies/{policy_id}/deviceStatuses"

# ── Config policies ────────────────────────────────────────────────────────
DEVICE_CONFIGURATIONS        = "deviceManagement/deviceConfigurations"
DEVICE_CONFIG_ASSIGNMENTS    = "deviceManagement/deviceConfigurations/{config_id}/assignments"
DEVICE_CONFIG_DEVICE_STATUS  = "deviceManagement/deviceConfigurations/{config_id}/deviceStatuses"

# ── Settings Catalog / Endpoint Security (beta) ───────────────────────────
SETTINGS_CATALOG_POLICIES    = "deviceManagement/configurationPolicies"
SETTINGS_CATALOG_ASSIGNMENTS = "deviceManagement/configurationPolicies/{policy_id}/assignments"

# ── Apps ───────────────────────────────────────────────────────────────────
MOBILE_APPS              = "deviceAppManagement/mobileApps"
APP_ASSIGNMENTS          = "deviceAppManagement/mobileApps/{app_id}/assignments"

# Per-device install status — endpoint differs by app type:
#   /deviceStatuses      → winGetApp, LOB, Store apps (beta)
#   /deviceInstallStates → Win32LobApp, windowsMobileMSI (beta)
#   NOTE: some tenants' win32LobApp apps return 400 on /deviceInstallStates
#         and must fall back to /deviceStatuses (see apps.py).
APP_DEVICE_STATUSES      = "deviceAppManagement/mobileApps/{app_id}/deviceStatuses"
APP_WIN32_INSTALL_STATES = "deviceAppManagement/mobileApps/{app_id}/deviceInstallStates"

# ── Groups ─────────────────────────────────────────────────────────────────
GROUPS                   = "groups"
GROUP_MEMBERS            = "groups/{group_id}/members"
USER_TRANSITIVE_MEMBEROF = "users/{user_id}/transitiveMemberOf"

# ── Organization ───────────────────────────────────────────────────────────
ORGANIZATION = "organization"
USER_DEVICES = "users/{user_id}/managedDevices"

# ─────────────────────────────────────────────────────────────────────────────
# $select field lists
# ─────────────────────────────────────────────────────────────────────────────

# managedDevice — verified valid fields
DEVICE_SELECT_FIELDS = ",".join([
    "id", "deviceName", "serialNumber",
    "operatingSystem", "osVersion", "complianceState",
    "managementState", "managedDeviceOwnerType",
    "enrolledDateTime", "lastSyncDateTime",
    "userPrincipalName", "userDisplayName", "userId",
    "azureADDeviceId", "model", "manufacturer", "imei",
    "totalStorageSpaceInBytes", "freeStorageSpaceInBytes",
    "isEncrypted", "jailBroken", "enrollmentProfileName",
])

# deviceCompliancePolicy
COMPLIANCE_POLICY_SELECT_FIELDS = ",".join([
    "id", "displayName", "description", "createdDateTime",
    "lastModifiedDateTime", "version",
])

# deviceConfiguration
DEVICE_CONFIG_SELECT_FIELDS = ",".join([
    "id", "displayName", "description", "createdDateTime",
    "lastModifiedDateTime", "version",
])

# mobileApp — $select intentionally NOT used (APP_SELECT_FIELDS = None).
#
# /deviceAppManagement/mobileApps is a polymorphic collection: app types
# (winGetApp, win32LobApp, officeSuiteApp, windowsMicrosoftEdgeApp, …) each
# have a different OData schema. Using $select on a mixed-type collection
# causes Graph to silently drop any app whose derived type does not declare
# ALL the requested fields — resulting in partial app lists (e.g. winGetApp
# and officeSuiteApp missing while win32LobApp appears).
# Requesting all fields (no $select) guarantees every app type is returned.
APP_SELECT_FIELDS = None   # None → no $select applied in apps.py

# group
GROUP_SELECT_FIELDS = ",".join([
    "id", "displayName", "description", "groupTypes",
    "mail", "membershipRule", "membershipRuleProcessingState",
])

# deviceComplianceDeviceStatus — managedDeviceId NOT exposed here
COMPLIANCE_STATUS_SELECT = ",".join([
    "id", "deviceDisplayName", "status",
    "lastReportedDateTime", "userName", "userPrincipalName",
])
