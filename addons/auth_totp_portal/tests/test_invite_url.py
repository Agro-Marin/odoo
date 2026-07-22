"""Tests for the portal-specific TOTP invite URL."""

from odoo.tests import TransactionCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user


@tagged("post_install", "-at_install")
class TestInviteUrl(TransactionCase):
    def test_portal_user_gets_my_security_url(self):
        """A portal user is pointed at the portal security page."""
        portal_user = mail_new_test_user(
            self.env,
            login="totp_portal_url",
            email="totp.portal.url@example.com",
            groups="base.group_portal",
        )
        self.assertEqual(portal_user.get_totp_invite_url(), "/my/security")

    def test_internal_user_delegates_to_super(self):
        """An internal user keeps the backend invite URL (boundary)."""
        internal_user = mail_new_test_user(
            self.env,
            login="totp_internal_url",
            email="totp.internal.url@example.com",
            groups="base.group_user",
        )
        self.assertNotEqual(internal_user.get_totp_invite_url(), "/my/security")
