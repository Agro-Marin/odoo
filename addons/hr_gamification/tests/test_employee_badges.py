"""Tests for the employee badge aggregation."""

from odoo.tests import TransactionCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user


@tagged("post_install", "-at_install")
class TestEmployeeBadges(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = mail_new_test_user(
            cls.env,
            login="badge_user",
            email="badge.user@example.com",
            groups="base.group_user",
        )
        cls.employee = cls.env["hr.employee"].create(
            {"name": "Badge employee", "user_id": cls.user.id}
        )
        cls.badge = cls.env["gamification.badge"].create({"name": "HR Star"})

    def test_no_badges_flag_false(self):
        """An employee without badges reports has_badges False (boundary)."""
        self.employee.invalidate_recordset(["badge_ids", "has_badges"])
        self.assertFalse(self.employee.has_badges)
        self.assertFalse(self.employee.badge_ids)

    def test_badge_through_user_is_aggregated(self):
        """A badge granted to the employee's user is aggregated on the employee."""
        badge_user = self.env["gamification.badge.user"].create(
            {"badge_id": self.badge.id, "user_id": self.user.id}
        )
        self.employee.invalidate_recordset(["badge_ids", "has_badges"])
        self.assertTrue(self.employee.has_badges)
        self.assertIn(badge_user, self.employee.badge_ids)
