"""
tests/test_intune_links.py

Pure-function unit tests for app/utils/intune_links.py.
No DB, no Qt, no network access required.

Run:
    python tests/test_intune_links.py
    # or, if pytest is available:
    python -m pytest tests/test_intune_links.py -v
"""
from __future__ import annotations

import sys
import os
import traceback

# Allow import from repo root without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.utils.intune_links import (
    _enc,
    _platform_int,
    _platform_name,
    compliance_policy_url,
    settings_catalog_url,
    windows_update_url,
    config_policy_url,
    app_url,
    remediation_url,
    device_intune_url,
    build_policy_url,
)

FAKE_ID = "1fe7ed4e-2c15-4fd4-ad3f-2a5931925121"

# ─────────────────────────────────────────────────────────────────────────────
# Minimal test runner (no pytest dependency)
# ─────────────────────────────────────────────────────────────────────────────

_tests: list[tuple[str, callable]] = []
_failures: list[str] = []


def test(fn):
    _tests.append((fn.__name__, fn))
    return fn


def _assert(cond: bool, msg: str = ""):
    if not cond:
        raise AssertionError(msg or "assertion failed")


# ─────────────────────────────────────────────────────────────────────────────
# _enc
# ─────────────────────────────────────────────────────────────────────────────

@test
def test_enc_plain():
    _assert(_enc("Hello") == "Hello")


@test
def test_enc_spaces():
    result = _enc("Enable Administrator Account")
    _assert(" " not in result, f"space found in {result!r}")
    _assert(result == "Enable%20Administrator%20Account", f"got {result!r}")


@test
def test_enc_slash():
    _assert("/" not in _enc("A/B"), "slash should be encoded")


@test
def test_enc_none_safe():
    _assert(_enc("") == "")
    _assert(_enc(None) == "")  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────────
# Platform helpers
# ─────────────────────────────────────────────────────────────────────────────

@test
def test_platform_int_windows():
    _assert(_platform_int("windows10") == 8)
    _assert(_platform_int("windows") == 8)


@test
def test_platform_int_ios():
    _assert(_platform_int("ios") == 2)


@test
def test_platform_int_android():
    _assert(_platform_int("android") == 4)


@test
def test_platform_int_macos():
    _assert(_platform_int("macos") == 16)
    _assert(_platform_int("osx") == 16)


@test
def test_platform_int_fallback():
    _assert(_platform_int("") == 8)
    _assert(_platform_int("unknown") == 8)


@test
def test_platform_int_comma():
    # "windows10,macOS" → first token = windows10 → 8
    _assert(_platform_int("windows10,macOS") == 8)


@test
def test_platform_name_windows():
    _assert(_platform_name("windows10") == "windows10")
    _assert(_platform_name("windows") == "windows10")


@test
def test_platform_name_ios():
    _assert(_platform_name("ios") == "iOS")


@test
def test_platform_name_macos():
    _assert(_platform_name("macos") == "macOS")


@test
def test_platform_name_fallback():
    _assert(_platform_name("") == "windows10")


# ─────────────────────────────────────────────────────────────────────────────
# compliance_policy_url
# ─────────────────────────────────────────────────────────────────────────────

@test
def test_compliance_contains_id():
    url = compliance_policy_url(FAKE_ID, "My Policy")
    _assert(FAKE_ID in url)


@test
def test_compliance_blade():
    url = compliance_policy_url(FAKE_ID, "My Policy")
    _assert("CompliancePolicyOverview.ReactView" in url, url)


@test
def test_compliance_namespace():
    url = compliance_policy_url(FAKE_ID, "My Policy")
    _assert("Microsoft_Intune_DeviceSettings" in url, url)


@test
def test_compliance_no_policy_summary():
    url = compliance_policy_url(FAKE_ID, "My Policy")
    _assert("PolicySummaryBlade" not in url, url)


@test
def test_compliance_platform_windows():
    url = compliance_policy_url(FAKE_ID, "My Policy", "windows10")
    _assert("/platform~/8" in url, url)


@test
def test_compliance_platform_ios():
    url = compliance_policy_url(FAKE_ID, "My Policy", "ios")
    _assert("/platform~/2" in url, url)


@test
def test_compliance_policy_type_35():
    url = compliance_policy_url(FAKE_ID, "My Policy")
    _assert("/policyType~/35" in url, url)


@test
def test_compliance_journey_state():
    url = compliance_policy_url(FAKE_ID, "My Policy")
    _assert("/policyJourneyState~/1" in url, url)


@test
def test_compliance_name_encoded():
    url = compliance_policy_url(FAKE_ID, "Enable Administrator Account")
    _assert("Enable%20Administrator%20Account" in url, url)


# ─────────────────────────────────────────────────────────────────────────────
# settings_catalog_url
# ─────────────────────────────────────────────────────────────────────────────

@test
def test_settings_namespace():
    url = settings_catalog_url(FAKE_ID)
    _assert("Microsoft_Intune_Workflows" in url, url)


@test
def test_settings_blade():
    url = settings_catalog_url(FAKE_ID)
    _assert("PolicySummaryBlade" in url, url)


@test
def test_settings_platform_ios():
    url = settings_catalog_url(FAKE_ID, platform="ios")
    _assert("platformName/iOS" in url, url)


@test
def test_settings_technology():
    url = settings_catalog_url(FAKE_ID, technology="endpointSecurity")
    _assert("technology/endpointSecurity" in url, url)


@test
def test_settings_is_assigned_true():
    url = settings_catalog_url(FAKE_ID, is_assigned=True)
    _assert("isAssigned~/true" in url, url)


@test
def test_settings_is_assigned_false():
    url = settings_catalog_url(FAKE_ID, is_assigned=False)
    _assert("isAssigned~/false" in url, url)


# ─────────────────────────────────────────────────────────────────────────────
# windows_update_url
# ─────────────────────────────────────────────────────────────────────────────

@test
def test_winupdate_blade():
    url = windows_update_url(FAKE_ID, "My Ring")
    _assert("SoftwareUpdatesConfigurationSummaryReportBlade" in url, url)


@test
def test_winupdate_type_windows():
    url = windows_update_url(FAKE_ID, "My Ring", is_macos=False)
    _assert("softwareUpdatesType/windows" in url, url)
    _assert("policyType/Windows10DesktopSoftwareUpdate" in url, url)


@test
def test_winupdate_type_macos():
    url = windows_update_url(FAKE_ID, "macOS Ring", is_macos=True)
    _assert("softwareUpdatesType/macOS" in url, url)
    _assert("policyType/macOSSoftwareUpdate" in url, url)


@test
def test_winupdate_name_encoded():
    url = windows_update_url(FAKE_ID, "My Update Ring")
    _assert("My%20Update%20Ring" in url, url)


# ─────────────────────────────────────────────────────────────────────────────
# config_policy_url
# ─────────────────────────────────────────────────────────────────────────────

@test
def test_config_blade():
    url = config_policy_url(FAKE_ID)
    _assert("DeviceConfigurationMenuBlade" in url, url)


@test
def test_config_no_policy_summary():
    url = config_policy_url(FAKE_ID)
    _assert("PolicySummaryBlade" not in url, url)


@test
def test_config_profile_id():
    url = config_policy_url(FAKE_ID)
    _assert(FAKE_ID in url)


# ─────────────────────────────────────────────────────────────────────────────
# app_url
# ─────────────────────────────────────────────────────────────────────────────

@test
def test_app_namespace():
    url = app_url(FAKE_ID)
    _assert("Microsoft_Intune_Apps" in url, url)


@test
def test_app_settings_menu():
    url = app_url(FAKE_ID)
    _assert("SettingsMenu/~/0" in url, url)


@test
def test_app_no_app_overview():
    url = app_url(FAKE_ID)
    _assert("AppOverview.ReactView" not in url, url)


@test
def test_app_id_present():
    url = app_url(FAKE_ID)
    _assert(FAKE_ID in url)


# ─────────────────────────────────────────────────────────────────────────────
# remediation_url
# ─────────────────────────────────────────────────────────────────────────────

@test
def test_remediation_blade():
    url = remediation_url(FAKE_ID)
    _assert("DeviceHealthScriptsMenuBlade" in url, url)


@test
def test_remediation_id():
    url = remediation_url(FAKE_ID)
    _assert(FAKE_ID in url)


# ─────────────────────────────────────────────────────────────────────────────
# device_intune_url
# ─────────────────────────────────────────────────────────────────────────────

@test
def test_device_namespace():
    url = device_intune_url(FAKE_ID)
    _assert("Microsoft_Intune_Devices" in url, url)


@test
def test_device_id():
    url = device_intune_url(FAKE_ID)
    _assert(FAKE_ID in url)


# ─────────────────────────────────────────────────────────────────────────────
# build_policy_url (no DB in test context → falls back to policy_type arg)
# ─────────────────────────────────────────────────────────────────────────────

@test
def test_build_compliance_dispatch():
    url = build_policy_url(FAKE_ID, "compliance_policy", "My Policy")
    _assert("CompliancePolicyOverview.ReactView" in url, url)
    _assert("PolicySummaryBlade" not in url, url)


@test
def test_build_settings_catalog_dispatch():
    url = build_policy_url(FAKE_ID, "settings_catalog", "My SC")
    _assert("PolicySummaryBlade" in url, url)


@test
def test_build_endpoint_security_dispatch():
    url = build_policy_url(FAKE_ID, "endpoint_security", "My ES")
    _assert("PolicySummaryBlade" in url, url)


@test
def test_build_config_policy_dispatch():
    url = build_policy_url(FAKE_ID, "config_policy", "Generic")
    _assert("DeviceConfigurationMenuBlade" in url, url)


@test
def test_build_unknown_no_crash():
    url = build_policy_url(FAKE_ID, "unknown_type", "Foobar")
    _assert(url.startswith("https://intune.microsoft.com"), url)


@test
def test_build_id_always_present():
    for pt in ("compliance_policy", "settings_catalog", "config_policy", "endpoint_security"):
        url = build_policy_url(FAKE_ID, pt, "Test")
        _assert(FAKE_ID in url, f"policy_id missing for type '{pt}': {url}")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    passed = 0
    for name, fn in _tests:
        try:
            fn()
            print(f"  ✓  {name}")
            passed += 1
        except Exception as exc:
            _failures.append(name)
            print(f"  ✗  {name}: {exc}")
            traceback.print_exc()

    print(f"\n{passed}/{len(_tests)} tests passed", end="")
    if _failures:
        print(f"  —  FAILED: {', '.join(_failures)}")
        sys.exit(1)
    else:
        print()
