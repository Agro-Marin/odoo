# Part of Odoo. See LICENSE file for full copyright and licensing details.
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

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
