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


@tagged("post_install", "-at_install")
class TestSignupWithToken(TransactionCase):
    """User creation and password change through res.users.signup tokens."""

    def test_signup_token_creates_user_for_partner(self):
        """A token for a user-less partner signs up a user and burns it."""
        partner = self.env["res.partner"].create(
            {"name": "Invitee", "email": "invitee@test.example.com"}
        )
        partner.signup_prepare()
        token = partner._generate_signup_token()

        login, _password = (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .signup(
                {"login": "invitee@test.example.com", "password": "SuperSecret!42"},
                token=token,
            )
        )

        self.assertEqual(login, "invitee@test.example.com")
        self.assertTrue(partner.user_ids)
        self.assertEqual(partner.user_ids.partner_id, partner)
        self.assertFalse(partner.signup_type)

    def test_signup_token_updates_existing_user(self):
        """A token for a partner WITH a user updates it, ignoring identity."""
        user = mail_new_test_user(
            self.env,
            name="Existing signup user",
            login="existing.signup@test.example.com",
            groups="base.group_portal",
        )
        user.partner_id.signup_prepare(signup_type="reset")
        token = user.partner_id._generate_signup_token()

        login, _password = (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .signup(
                {
                    "login": "hijack@test.example.com",
                    "name": "Hijacker",
                    "password": "NewSecret!42",
                },
                token=token,
            )
        )

        # identity fields are ignored: same login, same name
        self.assertEqual(login, "existing.signup@test.example.com")
        self.assertEqual(user.name, "Existing signup user")
        self.assertFalse(user.partner_id.signup_type)

    def test_burnt_token_rejected_on_second_use(self):
        """A signup token is single-use: the second signup must fail."""
        partner = self.env["res.partner"].create(
            {"name": "One shot", "email": "one.shot@test.example.com"}
        )
        partner.signup_prepare()
        token = partner._generate_signup_token()
        self.env["res.users"].with_context(no_reset_password=True).signup(
            {"login": "one.shot@test.example.com", "password": "FirstUse!42"},
            token=token,
        )

        with self.assertRaises(exceptions.UserError):
            self.env["res.users"].with_context(no_reset_password=True).signup(
                {"login": "again@test.example.com", "password": "SecondUse!42"},
                token=token,
            )

    def test_web_create_users_survives_email_less_inactive_user(self):
        """A login-only inactive user must not abort the batch invite."""
        Users = self.env["res.users"]
        email_less = Users.with_context(no_reset_password=True).create(
            {"name": "No email", "login": "noemail.match@test.example.com"}
        )
        self.assertFalse(email_less.email)
        self.assertEqual(email_less.state, "new")

        Users.web_create_users(
            ["noemail.match@test.example.com", "fresh@test.example.com"]
        )

        fresh = Users.search([("login", "=", "fresh@test.example.com")])
        self.assertTrue(fresh)
        self.assertEqual(fresh.state, "new")
