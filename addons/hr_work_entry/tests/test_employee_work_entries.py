"""Tests for the employee work-entry helpers."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestEmployeeWorkEntries(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["hr.employee"].create({"name": "WE employee"})

    def test_has_work_entries_false_without_entries(self):
        """A fresh employee reports no work entries (boundary)."""
        self.employee.invalidate_recordset(["has_work_entries"])
        self.assertFalse(self.employee.has_work_entries)

    def test_action_open_work_entries_targets_employee(self):
        """The work-entries action is scoped and defaulted to the employee."""
        action = self.employee.action_open_work_entries()
        self.assertEqual(action["res_model"], "hr.work.entry")
        self.assertIn(("employee_id", "=", self.employee.id), action["domain"])
        self.assertEqual(action["context"]["default_employee_id"], self.employee.id)

    def test_action_open_work_entries_forwards_initial_date(self):
        """An initial date is forwarded into the action context."""
        action = self.employee.action_open_work_entries(initial_date="2026-01-01")
        self.assertEqual(action["context"]["initial_date"], "2026-01-01")
