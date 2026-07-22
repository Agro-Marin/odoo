"""Tests for the credential-category display name and count."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCredentialCategoryDisplay(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category = cls.env["credential.category"].create(
            {"name": "API Keys", "code": "bcm_test_api_key"}
        )

    def test_display_name_shows_name_and_code(self):
        """The display name combines the name and the technical code."""
        self.category.invalidate_recordset(["display_name"])
        self.assertEqual(self.category.display_name, "API Keys (bcm_test_api_key)")

    def test_credential_count_zero_without_credentials(self):
        """A fresh category reports a zero credential count (boundary)."""
        self.category.invalidate_recordset(["credential_count"])
        self.assertEqual(self.category.credential_count, 0)
