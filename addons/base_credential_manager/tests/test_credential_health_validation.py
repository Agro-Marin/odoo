"""Tests for credential health validation and the JSON key lookup.

This file arrived written against the certificate support that
credential.credential used to carry. That implementation was a partial
duplicate of the certificate module and has been removed -- X.509 material
lives on certificate.certificate / certificate.key, which own the parsing, the
cert/key compatibility constraint and the signing API.

So the certificate-specific cases are gone rather than ported: there is no
_get_certificate_der_bytes to format, no certificate branch in
action_validate_credential, and no 'certificate' category to file a credential
under. What remains here is everything whose subject survived -- the
not-implemented validation contract, the cron's scoping and error handling, and
get_credential_value_by_key. The encryption-at-rest equivalents of the deleted
cases live in certificate_encryption's own suite.
"""

import os
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class HealthValidationCommon(TransactionCase):
    """Shared fixtures: encryption key patch and categories."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_key = "7ftr9ALjwK7f4IqWwnpFxWx4Wn8vetsznoGT3Oh46eU="
        cls.env_patcher = patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": cls.test_key}
        )
        cls.env_patcher.start()
        cls.category_custom = cls.env.ref(
            "base_credential_manager.credential_category_custom"
        )

    @classmethod
    def tearDownClass(cls):
        cls.env_patcher.stop()
        super().tearDownClass()

    @classmethod
    def _make_credential(cls, name, **vals):
        """Create a plain credential under the 'custom' category."""
        return cls.env["credential.credential"].create(
            {
                "name": name,
                "category_id": cls.category_custom.id,
                **vals,
            },
        )


class TestActionValidateCredential(HealthValidationCommon):
    """There is no built-in probe left, and that must be said out loud."""

    def test_category_without_probe_stays_unknown(self):
        """Without a built-in probe the credential must NOT be marked healthy."""
        credential = self._make_credential("Custom cred without probe")

        result = credential.action_validate_credential()

        self.assertTrue(result["not_implemented"])
        self.assertFalse(result["success"])
        self.assertIn("No built-in validation", result["message"])
        self.assertEqual(credential.health_status, "unknown")
        self.assertIn("No built-in validation", credential.health_message)
        self.assertTrue(credential.last_health_check)


class TestCronValidateCredentials(HealthValidationCommon):
    """What the cron touches, and what it does when a probe explodes."""

    def test_cron_scopes_by_auto_validate_flag(self):
        """The cron only touches active auto-validate credentials."""
        probed = self._make_credential("Cron probed", auto_validate_health=True)
        excluded = self._make_credential("Cron excluded")
        # excluded keeps auto_validate_health at its default (False), so the
        # cron's domain must leave it untouched.

        result = self.env["credential.credential"].cron_validate_credentials()

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["errors"], 0)
        # Probed but with no built-in validator, so it is counted as skipped and
        # left at 'unknown' -- stamping 'healthy' on an unprobed credential
        # would be a lie.
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["healthy"], 0)
        self.assertEqual(probed.health_status, "unknown")
        self.assertTrue(probed.last_health_check)
        self.assertFalse(excluded.last_health_check)

    @mute_logger("odoo.addons.base_credential_manager.models.credential_credential")
    def test_cron_swallows_validation_exception(self):
        """An exception raised by action_validate_credential never propagates."""
        Credential = self.env["credential.credential"]
        credential = self._make_credential("Cron crashing", auto_validate_health=True)

        with patch.object(
            type(credential),
            "action_validate_credential",
            side_effect=ValueError("boom"),
        ):
            result = Credential.cron_validate_credentials()

        self.assertIsInstance(result, dict)
        self.assertEqual(result["errors"], 1)


class TestGetCredentialValueByKey(HealthValidationCommon):
    """Key lookup over the JSON credential payload."""

    def test_key_lookup_returns_value_and_default(self):
        """Present key returns its value; absent key returns the default."""
        credential = self.env["credential.credential"].create(
            {
                "name": "Basic auth for key lookup",
                "category_id": self.env.ref(
                    "base_credential_manager.credential_category_basic_auth"
                ).id,
                "username": "svc-user",
                "password": "svc-pass",
            },
        )
        self.assertEqual(credential.get_credential_value_by_key("username"), "svc-user")
        self.assertEqual(
            credential.get_credential_value_by_key("missing", default="dflt"),
            "dflt",
        )

    def test_simple_storage_never_synthesizes_dict_view(self):
        """A 'simple' storage credential falls back to the default, never a dict."""
        credential = self._make_credential(
            "Simple storage for key lookup",
            credential_value="secret-value",
        )

        self.assertEqual(credential.storage_method, "simple")
        self.assertEqual(
            credential.get_credential_value_by_key("value", default="dflt"),
            "dflt",
        )
