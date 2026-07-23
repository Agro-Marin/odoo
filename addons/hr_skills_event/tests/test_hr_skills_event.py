# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestHrSkillsEvent(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["hr.employee"].create({"name": "Trainee"})

    def _resume_line(self, course_type):
        return self.env["hr.resume.line"].create(
            {
                "employee_id": self.employee.id,
                "name": "Course",
                "course_type": course_type,
            }
        )

    def test_color_is_dedicated_for_onsite(self):
        """An onsite course line gets the module's dedicated colour."""
        self.assertEqual(self._resume_line("onsite").color, "#714a66")

    def test_color_falls_back_for_external(self):
        """A non-onsite course line keeps the base colour, not the onsite one."""
        self.assertEqual(self._resume_line("external").color, "#a2a2a2")

    def test_event_id_cleared_when_not_onsite(self):
        """The onsite event link is empty for a non-onsite course line."""
        self.assertFalse(self._resume_line("external").event_id)
