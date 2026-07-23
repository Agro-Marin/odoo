"""Tests for the partner signup-token lifecycle."""

from odoo import exceptions
from odoo.tests import TransactionCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user


@tagged("post_install", "-at_install")
class TestSignupToken(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create(
            {"name": "Signup partner", "email": "signup.partner@example.com"}
        )

    def test_token_round_trip_resolves_partner(self):
        """A prepared partner's token resolves back to the same partner."""
        self.partner.signup_prepare()
        token = self.partner._generate_signup_token()
        self.assertEqual(
            self.env["res.partner"]._signup_retrieve_partner(token), self.partner
        )

    def test_cancel_invalidates_token(self):
        """Cancelling the signup clears the type and kills the token."""
        self.partner.signup_prepare()
        token = self.partner._generate_signup_token()
        self.partner.signup_cancel()
        self.assertFalse(self.partner.signup_type)
        with self.assertRaises(exceptions.UserError):
            self.env["res.partner"]._signup_retrieve_partner(token)

    def test_garbage_token_rejected(self):
        """An arbitrary token never resolves (negative)."""
        with self.assertRaises(exceptions.UserError):
            self.env["res.partner"]._signup_retrieve_partner("not-a-real-token")

    def test_retrieve_info_without_user_offers_email(self):
        """For a partner with no user, the email doubles as proposed login."""
        self.partner.signup_prepare()
        token = self.partner._generate_signup_token()
        info = self.env["res.partner"]._signup_retrieve_info(token)
        self.assertEqual(info["name"], "Signup partner")
        self.assertEqual(info["login"], "signup.partner@example.com")
        self.assertEqual(info["email"], "signup.partner@example.com")

    def test_retrieve_info_with_user_exposes_login(self):
        """For a partner with a user, the existing login is returned."""
        user = mail_new_test_user(
            self.env,
            login="signup_existing",
            email="signup.existing@example.com",
            groups="base.group_user",
        )
        user.partner_id.signup_prepare()
        token = user.partner_id._generate_signup_token()
        info = self.env["res.partner"]._signup_retrieve_info(token)
        self.assertEqual(info["login"], "signup_existing")
