"""
app/utils/intune_links.py

Single source of truth for ALL Intune / Entra portal deep-links.

Rules:
  1. Pure builder functions (no DB, no I/O, no Qt) are fully unit-testable.
  2. Smart openers (open_*) read DB metadata then call the pure builders.
  3. Nothing else in the codebase constructs portal URLs — all callers import here.

v1.2.1: Removed remediation_url() and open_remediation_portal()
        (Proactive Remediations feature removed).
"""

from __future__ import annotations

import json
import logging
import webbrowser
from urllib.parse import quote

logger = logging.getLogger(__name__)

INTUNE_BASE = "https://intune.microsoft.com/#view"

# ─────────────────────────────────────────────────────────────────────────────
# Platform normalisation tables
# ─────────────────────────────────────────────────────────────────────────────

_COMPLIANCE_PLATFORM_INT: dict[str, int] = {
    "windows":   8,
    "windows10": 8,
    "ios":       2,
    "android":   4,
    "macos":     16,
    "osx":       16,
    "all":       8,
}

_SETTINGS_PLATFORM_NAME: dict[str, str] = {
    "windows":   "windows10",
    "windows10": "windows10",
    "ios":       "iOS",
    "android":   "android",
    "macos":     "macOS",
    "osx":       "macOS",
    "all":       "windows10",
}

_WIN_UPDATE_ODATA = (
    "windowsupdateforbusinessconfiguration",
    "windowsupdatecatalogitem",
    "windowsdriverupdateprofile",
)
_MACOS_UPDATE_ODATA = (
    "macossoftwareupdateconfiguration",
    "macossoftwareupdateaccountsummary",
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _enc(s: str | None) -> str:
    return quote(str(s or ""), safe="")


def _platform_int(raw: str) -> int:
    first = (raw or "").split(",")[0].strip().lower()
    return _COMPLIANCE_PLATFORM_INT.get(first, 8)


def _platform_name(raw: str) -> str:
    first = (raw or "").split(",")[0].strip().lower()
    return _SETTINGS_PLATFORM_NAME.get(first, first or "windows10")


# ─────────────────────────────────────────────────────────────────────────────
# Pure URL builders
# ─────────────────────────────────────────────────────────────────────────────

def compliance_policy_url(
    policy_id: str,
    display_name: str = "",
    platform: str = "windows10",
) -> str:
    p_int = _platform_int(platform)
    return (
        f"{INTUNE_BASE}/Microsoft_Intune_DeviceSettings"
        f"/CompliancePolicyOverview.ReactView"
        f"/policyId/{policy_id}"
        f"/policyName/{_enc(display_name)}"
        f"/platform~/{p_int}"
        f"/policyType~/35"
        f"/policyJourneyState~/1"
    )


def settings_catalog_url(
    policy_id: str,
    is_assigned: bool = True,
    technology: str = "mdm",
    template_id: str = "",
    platform: str = "windows10",
) -> str:
    return (
        f"{INTUNE_BASE}/Microsoft_Intune_Workflows"
        f"/PolicySummaryBlade"
        f"/policyId/{policy_id}"
        f"/isAssigned~/{'true' if is_assigned else 'false'}"
        f"/technology/{technology}"
        f"/templateId/{template_id}"
        f"/platformName/{_platform_name(platform)}"
    )


def windows_update_url(
    policy_id: str,
    display_name: str = "",
    is_macos: bool = False,
) -> str:
    sw_type = "macOS" if is_macos else "windows"
    policy_type_str = "macOSSoftwareUpdate" if is_macos else "Windows10DesktopSoftwareUpdate"
    journey = "macOSUpdates" if is_macos else "WindowsUpdates"
    enc_name = _enc(display_name)
    return (
        f"{INTUNE_BASE}/Microsoft_Intune_DeviceSettings"
        f"/SoftwareUpdatesConfigurationSummaryReportBlade"
        f"/id/{policy_id}"
        f"/softwareUpdatesType/{sw_type}"
        f"/configurationName/{enc_name}"
        f"/policyId/{policy_id}"
        f"/policyType/{policy_type_str}"
        f"/policyJourneyState/{journey}"
        f"/policyName/{enc_name}"
    )


def config_policy_url(policy_id: str) -> str:
    return (
        f"{INTUNE_BASE}/Microsoft_Intune_DeviceSettings"
        f"/DeviceConfigurationMenuBlade/~/deviceConfigurationProfile"
        f"/profileId/{policy_id}"
    )


def app_url(app_id: str) -> str:
    return (
        f"{INTUNE_BASE}/Microsoft_Intune_Apps"
        f"/SettingsMenu/~/0/appId/{app_id}"
    )


def device_intune_url(device_id: str) -> str:
    return (
        f"{INTUNE_BASE}/Microsoft_Intune_Devices"
        f"/DeviceSettingsMenuBlade/~/overview"
        f"/mdmDeviceId/{device_id}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DB metadata loader
# ─────────────────────────────────────────────────────────────────────────────

def _load_control_meta(policy_id: str) -> dict:
    meta: dict = {}
    try:
        from app.db.database import session_scope
        from app.db.models import Control

        with session_scope() as db:
            ctrl = db.get(Control, policy_id)
            if not ctrl:
                return meta

            raw: dict = {}
            if ctrl.raw_json:
                try:
                    raw = json.loads(ctrl.raw_json) if isinstance(ctrl.raw_json, str) else {}
                except Exception:
                    pass

            meta["display_name"] = ctrl.display_name or ""
            meta["control_type"] = ctrl.control_type or ""
            meta["platform"] = ctrl.platform or ""
            meta["is_assigned"] = bool(ctrl.is_assigned)
            meta["odata_type"] = (raw.get("@odata.type") or "").lower()
            meta["technologies"] = raw.get("technologies") or ""
            meta["platforms_field"] = raw.get("platforms") or ""
            tmpl = raw.get("templateReference") or {}
            meta["template_id"] = (tmpl.get("templateId") or "") if isinstance(tmpl, dict) else ""

    except Exception as e:
        logger.debug(f"intune_links._load_control_meta failed for {policy_id}: {e}")

    return meta


# ─────────────────────────────────────────────────────────────────────────────
# Smart policy URL builder
# ─────────────────────────────────────────────────────────────────────────────

def build_policy_url(
    policy_id: str,
    policy_type: str = "",
    display_name: str = "",
) -> str:
    meta = _load_control_meta(policy_id)

    ctrl_type = meta.get("control_type") or policy_type
    name = meta.get("display_name") or display_name
    platform = meta.get("platform") or "windows10"
    is_assigned = meta.get("is_assigned", True)
    odata_type = meta.get("odata_type", "")
    technologies = meta.get("technologies", "")
    platforms_field = meta.get("platforms_field", "")
    template_id = meta.get("template_id", "")

    ct = ctrl_type.lower()

    if ct == "compliance_policy":
        if "ios" in odata_type:
            platform = "ios"
        elif "android" in odata_type:
            platform = "android"
        elif "macos" in odata_type or "osx" in odata_type:
            platform = "macos"
        elif "windows" in odata_type:
            platform = "windows10"
        return compliance_policy_url(policy_id, name, platform)

    elif ct in ("settings_catalog", "endpoint_security"):
        eff_platform = platforms_field or platform
        tech = (technologies.split(",")[0].strip()) if technologies else "mdm"
        return settings_catalog_url(
            policy_id,
            is_assigned=is_assigned,
            technology=tech,
            template_id=template_id,
            platform=eff_platform,
        )

    elif ct == "config_policy":
        if any(tok in odata_type for tok in _WIN_UPDATE_ODATA):
            return windows_update_url(policy_id, name, is_macos=False)
        if any(tok in odata_type for tok in _MACOS_UPDATE_ODATA):
            return windows_update_url(policy_id, name, is_macos=True)
        return config_policy_url(policy_id)

    else:
        if "compliance" in name.lower():
            return compliance_policy_url(policy_id, name, platform)
        return config_policy_url(policy_id)


# ─────────────────────────────────────────────────────────────────────────────
# Convenience openers
# ─────────────────────────────────────────────────────────────────────────────

def open_policy_portal(
    policy_id: str,
    policy_type: str = "",
    display_name: str = "",
) -> None:
    url = build_policy_url(policy_id, policy_type, display_name)
    logger.debug(f"Opening policy portal: {url}")
    webbrowser.open(url)


def open_app_portal(app_id: str) -> None:
    url = app_url(app_id)
    logger.debug(f"Opening app portal: {url}")
    webbrowser.open(url)


def open_device_portal(device_id: str) -> None:
    url = device_intune_url(device_id)
    logger.debug(f"Opening device portal: {url}")
    webbrowser.open(url)
