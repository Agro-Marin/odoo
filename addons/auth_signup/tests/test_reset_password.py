# Part of Odoo. See LICENSE file for full copyright and licensing details.
from contextlib import contextmanager
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from odoo import http
from odoo.exceptions import UserError
from odoo.tests.common import HttpCase

from odoo.addons.mail.models.mail_mail import MailDeliveryException


class TestResetPassword(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_user = cls.env['res.users'].create({
            'login': 'test',
            'name': 'The King',
            'email': 'noop@example.com',
        })

    def test_reset_password(self):
        """Signup URL carries 'signup_email' in its query; a password-reset URL does not."""

        # 'signup_email' lets the web controller (web_auth_reset_password) tell a
        # first-time signup from a later password reset.
        self.assertEqual(self.test_user.email, parse_qs(urlsplit(self.test_user.with_context(create_user=True).partner_id._get_signup_url()).query)["signup_email"][0], "query must contain 'signup_email'")

        # Invalidate signup_url to skip signup process
        self.env.invalidate_all()
        self.test_user.action_reset_password()

        self.assertNotIn("signup_email", parse_qs(urlsplit(self.test_user.partner_id._get_signup_url()).query), "query should not contain 'signup_email'")

    def test_reset_password_unknown_login_raises_usererror(self):
        """`reset_password` must raise UserError (an expected business error),
        not a bare Exception, for an unknown/ambiguous login (ruff TRY002)."""
        with self.assertRaises(UserError):
            self.env['res.users'].reset_password('no-such-login-at-all')

    @contextmanager
    def _patch_captcha_reset(self):
        def _verify_request_recaptcha_token(self, captcha):
            if captcha != 'password_reset':
                raise UserError("CAPTCHA test")
        with patch.object(self.env.registry['ir.http'], '_verify_request_recaptcha_token', _verify_request_recaptcha_token):
            yield

    def test_reset_password_no_account_enumeration(self):
        """A reset-password POST for a login that doesn't exist must show the
        exact same generic message as one for a login that does - a
        distinguishable error message here is a classic account/email
        enumeration oracle on the password-recovery flow."""
        self.env['ir.config_parameter'].sudo().set_param('auth_signup.reset_password', 'True')
        self.authenticate(None, None)
        csrf_token = http.Request.csrf_token(self)
        generic_message = b"Password reset instructions sent to your email address."

        with self._patch_captcha_reset():
            response_valid = self.url_open('/web/reset_password', data={
                'login': self.test_user.login,
                'csrf_token': csrf_token,
            })
            response_unknown = self.url_open('/web/reset_password', data={
                'login': 'no-such-login-at-all',
                'csrf_token': csrf_token,
            })

        self.assertNotIn(b'No account found', response_unknown.content)
        self.assertNotIn(b'Multiple accounts found', response_unknown.content)
        self.assertIn(generic_message, response_valid.content)
        self.assertIn(generic_message, response_unknown.content)

    @patch('odoo.addons.mail.models.mail_mail.MailMail.send')
    def test_reset_password_mail_server_error(self, mock_send):
        """action_reset_password() wraps a mail delivery failure in a UserError; _action_reset_password() lets the MailDeliveryException propagate."""

        mock_send.side_effect = MailDeliveryException(
            "Unable to connect to SMTP Server",
            ConnectionRefusedError("111, 'Connection refused'"),
        )
        with self.assertRaises(UserError) as cm1:
            self.test_user.action_reset_password()

        self.assertEqual(
            str(cm1.exception),
            "Could not contact the mail server, please check your outgoing email server configuration",
        )

        mock_send.side_effect = MailDeliveryException(
            "Unable to connect to SMTP Server",
            ValueError("[Errno -2] Name or service not known"),
        )
        with self.assertRaises(UserError) as cm2:
            self.test_user.action_reset_password()

        self.assertEqual(
            str(cm2.exception),
            "There was an error when trying to deliver your Email, please check your configuration",
        )

        # To check private method _action_reset_password() raises MailDeliveryException when there is no valid smtp server
        with self.assertRaises(MailDeliveryException):
            self.test_user._action_reset_password()
