"""Tests for the mail-2FA enforcement policy on users."""

from odoo.tests import TransactionCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user


@tagged("post_install", "-at_install")
class TestMfaPolicy(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.internal_user = mail_new_test_user(
            cls.env,
            login="totp_internal",
            email="totp.internal@example.com",
            groups="base.group_user",
        )
        cls.portal_user = mail_new_test_user(
            cls.env,
            login="totp_portal",
            email="totp.portal@example.com",
            groups="base.group_portal",
        )
        cls.icp = cls.env["ir.config_parameter"].sudo()

    def _set_policy(self, value):
        self.icp.set_param("auth_totp.policy", value)

    def test_no_policy_means_no_mail_mfa(self):
        """Without an enforcement policy, users have no forced mail 2FA."""
        self._set_policy(False)
        self.assertFalse(self.internal_user._mfa_type())

    def test_all_required_policy_covers_everyone(self):
        """The all_required policy enforces mail 2FA on any user."""
        self._set_policy("all_required")
        self.assertEqual(self.internal_user._mfa_type(), "totp_mail")
        self.assertEqual(self.portal_user._mfa_type(), "totp_mail")

    def test_employee_policy_covers_internal_users_only(self):
        """The employee_required policy skips portal users (boundary)."""
        self._set_policy("employee_required")
        self.assertEqual(self.internal_user._mfa_type(), "totp_mail")
        self.assertFalse(self.portal_user._mfa_type())

    def test_mfa_url_points_to_totp_login(self):
        """Users under mail 2FA are redirected to the totp login page."""
        self._set_policy("all_required")
        self.assertEqual(self.internal_user._mfa_url(), "/web/login/totp")

    def test_rpc_requires_api_keys_under_policy(self):
        """Password RPC is blocked (api-keys only) when mail 2FA applies."""
        self._set_policy("all_required")
        self.assertTrue(self.internal_user._rpc_api_keys_only())
        self._set_policy(False)
        self.assertFalse(self.internal_user._rpc_api_keys_only())
