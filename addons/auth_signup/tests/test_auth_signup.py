# Part of Odoo. See LICENSE file for full copyright and licensing details.

from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

import odoo
from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.base.tests.common import HttpCaseWithUserDemo, HttpCaseWithUserPortal


class TestAuthSignupFlow(HttpCaseWithUserPortal, HttpCaseWithUserDemo):
    def setUp(self):
        super().setUp()
        res_config = self.env["res.config.settings"]
        self.default_values = res_config.default_get(list(res_config.fields_get()))

    def _activate_free_signup(self):
        self.default_values.update({"auth_signup_uninvited": "b2c"})

    def _get_free_signup_url(self):
        return "/web/signup"

    @contextmanager
    def patch_captcha_signup(self):
        def _verify_request_recaptcha_token(self, captcha):
            if captcha != "signup":
                raise UserError("CAPTCHA test")

        with patch.object(
            self.env.registry["ir.http"],
            "_verify_request_recaptcha_token",
            _verify_request_recaptcha_token,
        ):
            yield

    def test_confirmation_mail_free_signup(self):
        """
        Check if a new user is informed by email when he is registered
        """

        # Activate free signup
        self._activate_free_signup()

        # Get csrf_token
        self.authenticate(None, None)
        csrf_token = http.Request.csrf_token(self)

        # Values from login form
        name = "toto"
        payload = {
            "login": "toto@example.com",
            "name": name,
            "password": "mypassword",
            "confirm_password": "mypassword",
            "csrf_token": csrf_token,
        }

        # Override unlink to not delete the email if the send works.
        with (
            patch.object(
                odoo.addons.mail.models.mail_mail.MailMail, "unlink", lambda self: None
            ),
            self.patch_captcha_signup(),
        ):
            # Call the controller
            url_free_signup = self._get_free_signup_url()
            response = self.url_open(url_free_signup, data=payload)
            self.assertIn("/web/login_successful?account_created=True", response.url)
            # Check if an email is sent to the new user
            new_user = self.env["res.users"].search([("name", "=", name)])
            self.assertTrue(new_user)
            mail = self.env["mail.message"].search(
                [
                    ("message_type", "=", "email_outgoing"),
                    ("model", "=", "res.users"),
                    ("res_id", "=", new_user.id),
                ],
                limit=1,
            )
            self.assertTrue(mail, "The new user must be informed of his registration")

    def test_compute_signup_url(self):
        user = self.user_demo
        user.group_ids -= self.env.ref("base.group_partner_manager")

        partner = self.partner_portal
        partner.signup_prepare()

        with self.assertRaises(AccessError):
            partner.with_user(user.id)._get_signup_url()

    def test_copy_multiple_users(self):
        users = self.env["res.users"].create(
            [
                {
                    "login": "testuser1",
                    "name": "Test User 1",
                    "email": "test1@odoo.com",
                },
                {
                    "login": "testuser2",
                    "name": "Test User 2",
                    "email": "test2@odoo.com",
                },
            ]
        )
        initial_user_count = self.env["res.users"].search_count([])
        users.copy()
        self.assertEqual(
            self.env["res.users"].search_count([]), initial_user_count + len(users)
        )

    def test_notify_unregistered(self):
        users = self.env["res.users"].create(
            [
                {
                    "login": "testuser1",
                    "name": "Test User 1",
                    "email": "test1@odoo.com",
                },
                {
                    "login": "testuser2",
                    "name": "Test User 2",
                    "email": "test2@odoo.com",
                },
            ]
        )
        for u in users:
            u.create_date = datetime.now() - timedelta(days=5, minutes=10)
        with self.registry.cursor() as cr:
            users.with_env(users.env(cr=cr)).send_unregistered_user_reminder(
                after_days=5, batch_size=100
            )


@tagged("post_install", "-at_install")
class TestSignupHttpRoutes(HttpCaseWithUserDemo):
    """HTTP gates and flows of the public signup / reset-password routes."""

    def _set_signup(self, scope):
        self.env["ir.config_parameter"].sudo().set_param(
            "auth_signup.invitation_scope",
            scope,
        )
        # With `website` installed the per-website field wins: its override of
        # _get_signup_invitation_scope (website/models/res_users.py) only falls
        # back to the parameter when auth_signup_uninvited is empty, and it
        # ships set to b2c. Closing only the parameter closes nothing.
        if "website" in self.env:
            self.env["website"].sudo().search([]).auth_signup_uninvited = scope

    def test_signup_disabled_is_not_found(self):
        """Without b2c and without token the signup page must 404."""
        self._set_signup("b2b")
        res = self.url_open("/web/signup")
        self.assertEqual(res.status_code, 404)

    def test_reset_password_disabled_is_not_found(self):
        """With the reset feature off and no token the route must 404."""
        self.env["ir.config_parameter"].sudo().set_param(
            "auth_signup.reset_password",
            "False",
        )
        res = self.url_open("/web/reset_password")
        self.assertEqual(res.status_code, 404)

    def test_signup_page_renders_with_frame_protection(self):
        """In b2c the page renders with the anti-framing headers."""
        self._set_signup("b2c")
        res = self.url_open("/web/signup")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertIn("frame-ancestors", res.headers.get("Content-Security-Policy", ""))

    def test_signup_post_creates_and_logs_in_user(self):
        """A valid b2c signup creates the user and opens a session."""
        self._set_signup("b2c")
        self.authenticate(None, None)
        res = self.url_open(
            "/web/signup",
            data={
                "login": "brand.new@example.com",
                "name": "Brand New",
                "password": "SuperSecret!123",
                "confirm_password": "SuperSecret!123",
                "csrf_token": http.Request.csrf_token(self),
            },
        )
        self.assertEqual(res.status_code, 200)
        user = (
            self.env["res.users"]
            .sudo()
            .search(
                [("login", "=", "brand.new@example.com")],
            )
        )
        self.assertTrue(user)
        self.assertEqual(user.name, "Brand New")

    def test_signup_post_password_mismatch_shows_error(self):
        """Mismatched passwords surface the form error, no user created."""
        self._set_signup("b2c")
        self.authenticate(None, None)
        res = self.url_open(
            "/web/signup",
            data={
                "login": "mismatch@example.com",
                "name": "Mismatch",
                "password": "SuperSecret!123",
                "confirm_password": "different",
                "csrf_token": http.Request.csrf_token(self),
            },
        )
        self.assertIn("Passwords do not match", res.text)
        self.assertFalse(
            self.env["res.users"]
            .sudo()
            .search(
                [("login", "=", "mismatch@example.com")],
            )
        )

    def test_signup_post_duplicate_email_shows_error(self):
        """Signing up with an existing login reports the duplicate."""
        self._set_signup("b2c")
        self.authenticate(None, None)
        res = self.url_open(
            "/web/signup",
            data={
                "login": self.user_demo.login,
                "name": "Impostor",
                "password": "SuperSecret!123",
                "confirm_password": "SuperSecret!123",
                "csrf_token": http.Request.csrf_token(self),
            },
        )
        self.assertIn("Another user is already registered", res.text)

    def test_reset_password_does_not_leak_account_existence(self):
        """Known and unknown logins get the SAME generic reset message."""
        self.env["ir.config_parameter"].sudo().set_param(
            "auth_signup.reset_password",
            "True",
        )
        self.authenticate(None, None)
        generic = "Password reset instructions sent to your email address."
        res_known = self.url_open(
            "/web/reset_password",
            data={
                "login": self.user_demo.login,
                "csrf_token": http.Request.csrf_token(self),
            },
        )
        self.assertIn(generic, res_known.text)
        # the known login actually got a reset token prepared
        self.assertEqual(
            self.user_demo.partner_id.sudo().signup_type,
            "reset",
        )

        res_unknown = self.url_open(
            "/web/reset_password",
            data={
                "login": "ghost.nobody@example.com",
                "csrf_token": http.Request.csrf_token(self),
            },
        )
        self.assertIn(generic, res_unknown.text)

    def test_signup_with_invalid_token_reports_it(self):
        """A garbage token renders the dedicated invalid-token error."""
        self._set_signup("b2b")
        res = self.url_open("/web/signup?token=not-a-real-token")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Invalid signup token", res.text)
