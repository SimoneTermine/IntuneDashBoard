"""
tests/test_auth.py

Minimal unit tests for:
  • DEFAULT_SCOPES — DeviceManagementConfiguration.Read.All is present
  • _has_required_scopes — ReadWrite.All satisfies a Read.All requirement
  • get_auth() — returns a singleton MSALAuth instance
  • admin_consent_url — produces correct URL shape
"""

import sys
import os
import unittest

# Make project root importable when running directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import DEFAULT_SCOPES
from app.graph.auth import MSALAuth, admin_consent_url, get_auth


class TestDefaultScopes(unittest.TestCase):

    def test_devicemanagementconfiguration_read_present(self):
        names = [s.split("/")[-1].lower() for s in DEFAULT_SCOPES]
        self.assertIn(
            "devicemanagementconfiguration.read.all",
            names,
            "DeviceManagementConfiguration.Read.All must be in DEFAULT_SCOPES",
        )

    def test_devicemanagementconfiguration_readwrite_present(self):
        names = [s.split("/")[-1].lower() for s in DEFAULT_SCOPES]
        self.assertIn(
            "devicemanagementconfiguration.readwrite.all",
            names,
            "DeviceManagementConfiguration.ReadWrite.All must be in DEFAULT_SCOPES",
        )


class TestHasRequiredScopes(unittest.TestCase):

    def _check(self, granted: str, requested: list) -> bool:
        """Helper: build a fake token result and call the static method."""
        result = {"scope": granted}
        return MSALAuth._has_required_scopes(result, requested)

    def test_exact_match(self):
        self.assertTrue(
            self._check(
                "devicemanagementconfiguration.read.all user.read",
                ["https://graph.microsoft.com/DeviceManagementConfiguration.Read.All"],
            )
        )

    def test_readwrite_satisfies_read(self):
        """
        Core regression test for the repeated-device-code bug.
        If the token has ReadWrite.All but the scope list requests Read.All,
        the silent path must succeed (return True).
        """
        self.assertTrue(
            self._check(
                "devicemanagementconfiguration.readwrite.all user.read",
                ["https://graph.microsoft.com/DeviceManagementConfiguration.Read.All"],
            )
        )

    def test_missing_scope_returns_false(self):
        self.assertFalse(
            self._check(
                "user.read",
                ["https://graph.microsoft.com/DeviceManagementConfiguration.Read.All"],
            )
        )

    def test_empty_granted_returns_false(self):
        self.assertFalse(
            self._check(
                "",
                ["https://graph.microsoft.com/DeviceManagementConfiguration.Read.All"],
            )
        )

    def test_oidc_scopes_always_pass(self):
        """openid / profile / offline_access must never block silent reuse."""
        self.assertTrue(
            self._check(
                "user.read",
                [
                    "https://graph.microsoft.com/openid",
                    "https://graph.microsoft.com/profile",
                    "https://graph.microsoft.com/offline_access",
                ],
            )
        )

    def test_multiple_scopes_all_required(self):
        granted = (
            "devicemanagementconfiguration.readwrite.all "
            "devicemanagementmanageddevices.read.all "
            "user.read"
        )
        requested = [
            "https://graph.microsoft.com/DeviceManagementConfiguration.Read.All",
            "https://graph.microsoft.com/DeviceManagementManagedDevices.Read.All",
        ]
        self.assertTrue(self._check(granted, requested))

    def test_partial_grant_returns_false(self):
        granted = "devicemanagementconfiguration.readwrite.all"
        requested = [
            "https://graph.microsoft.com/DeviceManagementConfiguration.Read.All",
            "https://graph.microsoft.com/DeviceManagementManagedDevices.Read.All",
        ]
        self.assertFalse(self._check(granted, requested))


class TestAdminConsentUrl(unittest.TestCase):

    def test_url_contains_client_id(self):
        url = admin_consent_url("my-client-id", "my-tenant-id")
        self.assertIn("my-client-id", url)

    def test_url_contains_tenant_id(self):
        url = admin_consent_url("cid", "tid-123")
        self.assertIn("tid-123", url)

    def test_empty_tenant_falls_back_to_common(self):
        url = admin_consent_url("cid", "")
        self.assertIn("/common/adminconsent", url)

    def test_common_tenant_stays_common(self):
        url = admin_consent_url("cid", "common")
        self.assertIn("/common/adminconsent", url)


class TestGetAuthSingleton(unittest.TestCase):

    def test_singleton_returns_same_instance(self):
        a = get_auth()
        b = get_auth()
        self.assertIs(a, b)

    def test_instance_is_msalauth(self):
        self.assertIsInstance(get_auth(), MSALAuth)


if __name__ == "__main__":
    unittest.main(verbosity=2)