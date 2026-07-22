"""Tests for the eLearning resume-line computes."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestResumeLine(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["hr.employee"].create({"name": "HSS employee"})
        cls.channel = cls.env["slide.channel"].create({"name": "HSS course"})
        cls.line_type = cls.env["hr.resume.line.type"].create({"name": "HSS type"})

    def _line(self, course_type, channel=None):
        return self.env["hr.resume.line"].create(
            {
                "employee_id": self.employee.id,
                "name": "HSS line",
                "line_type_id": self.line_type.id,
                "course_type": course_type,
                "channel_id": channel.id if channel else False,
            }
        )

    def test_channel_cleared_for_non_elearning(self):
        """A non-eLearning line drops any channel link."""
        line = self._line("external", channel=self.channel)
        self.assertFalse(line.channel_id)

    def test_channel_kept_for_elearning(self):
        """An eLearning line keeps its course channel."""
        line = self._line("elearning", channel=self.channel)
        self.assertEqual(line.channel_id, self.channel)

    def test_elearning_line_gets_course_color(self):
        """eLearning lines are tinted with the course color."""
        line = self._line("elearning", channel=self.channel)
        line.invalidate_recordset(["color"])
        self.assertEqual(line.color, "#00a5b7")
