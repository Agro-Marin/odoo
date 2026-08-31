from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestEmployeeWorkEntries(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["hr.employee"].create({"name": "WE employee"})

    def test_has_work_entries_false_without_entries(self):
        self.employee.invalidate_recordset(["has_work_entries"])
        self.assertFalse(self.employee.has_work_entries)

    def test_action_view_work_entries_targets_employee(self):
        action = self.employee.action_view_work_entries()
        self.assertEqual(action["res_model"], "hr.work.entry")
        self.assertIn(("employee_id", "=", self.employee.id), action["domain"])
        self.assertEqual(action["context"]["default_employee_id"], self.employee.id)

    def test_action_view_work_entries_forwards_initial_date(self):
        action = self.employee.action_view_work_entries(initial_date="2026-01-01")
        self.assertEqual(action["context"]["initial_date"], "2026-01-01")
