# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestHrGamificationBadges(TransactionCase):
    """Employee-linked gamification badges: counts, actions, access and guard."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # A fresh user avoids the one-employee-per-user unique constraint that
        # the admin's demo employee already occupies.
        cls.user = cls.env["res.users"].create(
            {"name": "Badge User", "login": "hr_badge_user"}
        )
        cls.employee = cls.env["hr.employee"].create(
            {"name": "Badge Employee", "user_id": cls.user.id}
        )
        cls.badge = cls.env["gamification.badge"].create({"name": "Star"})
        cls.badge_user = cls.env["gamification.badge.user"].create(
            {
                "badge_id": cls.badge.id,
                "user_id": cls.user.id,
                "employee_id": cls.employee.id,
            }
        )

    def test_granted_employees_count(self):
        """The badge counts distinct granted employees."""
        self.assertEqual(self.badge.granted_employees_count, 1)

    def test_get_granted_employees_action(self):
        """get_granted_employees targets the public employees of the badge."""
        action = self.badge.get_granted_employees()
        self.assertEqual(action["res_model"], "hr.employee.public")
        self.assertIn(self.employee.id, action["domain"][0][2])

    def test_action_open_badge(self):
        """action_open_badge opens the badge-user record in a dialog form."""
        action = self.badge_user.action_open_badge()
        self.assertEqual(action["res_model"], "gamification.badge.user")
        self.assertEqual(action["res_id"], self.badge_user.id)

    def test_hr_user_has_edit_delete_access(self):
        """An HR user has edit/delete access to badge users."""
        self.assertTrue(self.badge_user.has_edit_delete_access)

    def test_employee_user_mismatch_is_rejected(self):
        """A badge user whose employee belongs to another user is rejected."""
        other_user = self.env["res.users"].create(
            {"name": "Other", "login": "hr_badge_other"}
        )
        other_employee = self.env["hr.employee"].create(
            {"name": "Other Employee", "user_id": other_user.id}
        )
        with self.assertRaises(ValidationError):
            self.env["gamification.badge.user"].create(
                {
                    "badge_id": self.badge.id,
                    "user_id": self.user.id,
                    "employee_id": other_employee.id,
                }
            )
