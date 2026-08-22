# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestHrSkillsSlidesEmployee(TransactionCase):
    """hr.employee course-completion text and the open-courses action."""

    def test_completion_text_without_user_is_empty(self):
        """An employee with no linked user has no course completion text."""
        employee = self.env["hr.employee"].create({"name": "No User"})
        self.assertFalse(employee.user_id)
        self.assertFalse(employee.has_subscribed_courses)
        self.assertFalse(employee.courses_completion_text)

    def test_completion_text_with_user_no_courses(self):
        """A user with no subscribed courses shows a 0 / 0 completion text."""
        user = self.env["res.users"].create(
            {"name": "Learner", "login": "skills_slides_learner"}
        )
        employee = self.env["hr.employee"].create(
            {"name": "Learner Emp", "user_id": user.id}
        )
        self.assertEqual(employee.courses_completion_text, "0 / 0")
        self.assertFalse(employee.has_subscribed_courses)

    def test_action_view_courses_targets_profile(self):
        """The open-courses action points at the user's profile URL."""
        user = self.env["res.users"].create(
            {"name": "Learner 2", "login": "skills_slides_learner2"}
        )
        employee = self.env["hr.employee"].create(
            {"name": "Learner Emp 2", "user_id": user.id}
        )
        action = employee.action_open_courses()
        self.assertEqual(action["type"], "ir.actions.act_url")
        self.assertIn(str(user.id), action["url"])
