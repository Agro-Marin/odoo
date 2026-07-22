"""Tests for the email-validation token flow on user profiles."""

from odoo.tests import TransactionCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user
from odoo.addons.website_profile.models.res_users import VALIDATION_KARMA_GAIN


@tagged("post_install", "-at_install")
class TestProfileValidation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = mail_new_test_user(
            cls.env,
            login="wp_profile_user",
            email="wp.profile@example.com",
            groups="base.group_user",
        )

    def test_token_is_deterministic_per_day(self):
        """The same user/email pair yields a stable token within the day."""
        Users = self.env["res.users"]
        token_1 = Users._generate_profile_token(self.user.id, self.user.email)
        token_2 = Users._generate_profile_token(self.user.id, self.user.email)
        self.assertEqual(token_1, token_2)

    def test_token_differs_per_email(self):
        """Changing the email changes the token."""
        Users = self.env["res.users"]
        token_1 = Users._generate_profile_token(self.user.id, "a@example.com")
        token_2 = Users._generate_profile_token(self.user.id, "b@example.com")
        self.assertNotEqual(token_1, token_2)

    def test_valid_token_grants_validation_karma(self):
        """A matching token on a zero-karma user grants the karma bonus."""
        self.user.karma = 0
        token = self.env["res.users"]._generate_profile_token(
            self.user.id, self.user.email
        )
        self.assertTrue(
            self.user._process_profile_validation_token(token, self.user.email)
        )
        self.assertEqual(self.user.karma, VALIDATION_KARMA_GAIN)

    def test_wrong_token_is_rejected(self):
        """A forged token never grants karma (boundary)."""
        self.user.karma = 0
        self.assertFalse(
            self.user._process_profile_validation_token("forged", self.user.email)
        )
        self.assertEqual(self.user.karma, 0)

    def test_token_on_active_user_is_rejected(self):
        """A user with existing karma cannot re-validate (boundary)."""
        self.user.karma = 10
        token = self.env["res.users"]._generate_profile_token(
            self.user.id, self.user.email
        )
        self.assertFalse(
            self.user._process_profile_validation_token(token, self.user.email)
        )
        self.assertEqual(self.user.karma, 10)

    def test_validation_email_requires_an_email(self):
        """Users without an email address cannot be sent a validation mail."""
        self.user.email = False
        self.assertFalse(self.user._send_profile_validation_email())
