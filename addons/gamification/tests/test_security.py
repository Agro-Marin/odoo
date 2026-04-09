from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import common

from odoo.addons.mail.tests.common import mail_new_test_user


class TestSecurityRules(common.TransactionCase):
    """Tests for ir.rule security rules on gamification models."""

    @classmethod
    def setUpClass(cls):
        """Set up two standard users and shared test data."""
        super().setUpClass()
        patch_email = patch(
            "odoo.addons.mail.models.mail_template.MailTemplate.send_mail",
            lambda *args, **kwargs: None,
        )
        cls.startClassPatcher(patch_email)

        cls.user_a = mail_new_test_user(
            cls.env,
            login="sec_user_a",
            name="Security User A",
            email="sec_a@example.com",
            karma=0,
            groups="base.group_user",
        )
        cls.user_b = mail_new_test_user(
            cls.env,
            login="sec_user_b",
            name="Security User B",
            email="sec_b@example.com",
            karma=0,
            groups="base.group_user",
        )

        # Streak type setup (required for streak records)
        partner_model = cls.env["ir.model"]._get("res.partner")
        date_field = cls.env["ir.model.fields"].search(
            [("model", "=", "res.partner"), ("name", "=", "write_date")],
            limit=1,
        )
        cls.streak_type = cls.env["gamification.streak.type"].create({
            "name": "Test Streak Type",
            "model_id": partner_model.id,
            "date_field_id": date_field.id,
            "domain": "[('create_uid', '=', user.id)]",
            "karma_bonus": 5,
            "freeze_allowance": 1,
        })

        # Kudos category
        cls.kudos_category = cls.env.ref("gamification.kudos_category_teamwork")

    def test_streak_user_write_rule(self):
        """Users cannot modify another user's streak record."""
        streak = self.env["gamification.streak"].create({
            "user_id": self.user_a.id,
            "streak_type_id": self.streak_type.id,
        })
        with self.assertRaises(AccessError):
            streak.with_user(self.user_b).write({"freeze_remaining": 5})

    def test_kudos_user_write_rule(self):
        """Users cannot modify kudos sent by another user."""
        kudos = self.env["gamification.kudos"].with_user(self.user_a).create({
            "sender_id": self.user_a.id,
            "recipient_id": self.user_b.id,
            "category_id": self.kudos_category.id,
            "message": "Great work!",
        })
        with self.assertRaises(AccessError):
            kudos.with_user(self.user_b).write({"message": "Tampered!"})

    def test_karma_tracking_system_only(self):
        """Non-system users cannot read karma tracking records."""
        # Create a tracking record as superuser
        self.env["gamification.karma.tracking"].create({
            "user_id": self.user_a.id,
            "old_value": 0,
            "new_value": 10,
        })
        with self.assertRaises(AccessError):
            self.env["gamification.karma.tracking"].with_user(self.user_a).search([])
