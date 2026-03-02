"""
app/graph/endpoints.py

Graph API endpoint definitions.
All $select field lists have been verified against the microsoft.graph schema.

v1.2.1: Removed DEVICE_HEALTH_SCRIPTS, DEVICE_REMEDIATION_RUN,
        REMEDIATION_SELECT_FIELDS (Proactive Remediations feature removed).
"""

# ── Devices ────────────────────────────────────────────────────────────────
MANAGED_DEVICES          = "deviceManagement/managedDevices"
MANAGED_DEVICE_BY_ID     = "deviceManagement/managedDevices/{device_id}"

# ── Compliance policies ────────────────────────────────────────────────────
DEVICE_COMPLIANCE_POLICIES      = "deviceManagement/deviceCompliancePolicies"
DEVICE_COMPLIANCE_POLICY_BY_ID  = "deviceManagement/deviceCompliancePolicies/{policy_id}"
DEVICE_COMPLIANCE_ASSIGNMENTS   = "deviceManagement/deviceCompliancePolicies/{policy_id}/assignments"
# NOTE: deviceComplianceDeviceStatus does NOT expose managedDeviceId in $select.
# Use deviceDisplayName to correlate. See compliance_status.py for details.
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
#   /deviceStatuses      → iOS LOB, Android LOB, Managed Store apps, winGetApp (beta)
#   /deviceInstallStates → Win32LobApp, windowsMobileMSI (beta)
APP_DEVICE_STATUSES      = "deviceAppManagement/mobileApps/{app_id}/deviceStatuses"
APP_WIN32_INSTALL_STATES = "deviceAppManagement/mobileApps/{app_id}/deviceInstallStates"

# ── Groups ─────────────────────────────────────────────────────────────────
GROUPS                   = "groups"
GROUP_MEMBERS            = "groups/{group_id}/members"
# NOTE: Only use users/{id}/transitiveMemberOf (requires User.Read.All — already in scope).
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

# mobileApp — isAssigned and appType NOT valid $select fields
APP_SELECT_FIELDS = ",".join([
    "id", "displayName", "publisher", "description",
    "lastModifiedDateTime",
])

# group
GROUP_SELECT_FIELDS = ",".join([
    "id", "displayName", "description", "groupTypes",
    "mail", "membershipRule", "membershipRuleProcessingState",
])

# deviceComplianceDeviceStatus — managedDeviceId NOT exposed here
# Use deviceDisplayName to correlate with synced devices
COMPLIANCE_STATUS_SELECT = ",".join([
    "id", "deviceDisplayName", "status",
    "lastReportedDateTime", "userName", "userPrincipalName",
])
