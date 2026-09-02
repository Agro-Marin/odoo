from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAttendanceDependsCompleteness(TransactionCase):
    def test_display_name_follows_display_type(self):
        attendance = self.env["resource.calendar.attendance"].search([], limit=1)
        self.assertTrue(attendance, "need a calendar attendance to probe")
        self.assertDependsComplete(
            attendance,
            computed_fields=["display_name"],
            probe_fields=["display_type", "name"],
        )
