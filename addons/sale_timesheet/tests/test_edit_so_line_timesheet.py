from odoo.tests import tagged

from .common import TestCommonSaleTimesheet


@tagged("-at_install", "post_install")
class TestEditSoLineTimesheet(TestCommonSaleTimesheet):
    def setUp(self):
        super().setUp()
        self.task_rate_task = self.env["project.task"].create(
            {
                "name": "Task",
                "project_id": self.project_task_rate.id,
                "sale_line_id": self.so.line_ids[0].id,
            }
        )

    def test_sol_no_change_if_edited(self):
        timesheet = self.env["account.analytic.line"].create(
            {
                "name": "Test Line",
                "auto_account_id": self.analytic_account_sale.id,
                "project_id": self.project_task_rate.id,
                "task_id": self.task_rate_task.id,
                "unit_amount": 5,
                "employee_id": self.employee_manager.id,
            }
        )
        timesheet._compute_so_line()
        edited_timesheet = timesheet.copy()
        self.assertTrue(
            timesheet.so_line
            == edited_timesheet.so_line
            == self.task_rate_task.sale_line_id,
            "SOL in timesheet should be the same than the one in the task.",
        )
        self.assertEqual(
            timesheet.unit_amount + edited_timesheet.unit_amount,
            self.task_rate_task.sale_line_id.qty_transferred,
            "The quantity timesheeted should be increased the quantity delivered in the linked SOL.",
        )

        edited_timesheet.write(
            {
                "is_so_line_edited": True,
                "so_line": self.so.line_ids[1].id,
            }
        )
        self.so.line_ids._compute_qty_transferred()

        self.assertNotEqual(
            edited_timesheet.so_line,
            self.task_rate_task.sale_line_id,
            "SOL in timesheet should be different than the one in the task.",
        )
        self.assertEqual(
            edited_timesheet.so_line,
            self.so.line_ids[1],
            "SOL in timesheet is the one selected when we manually edit in the timesheet",
        )
        self.assertEqual(
            self.task_rate_task.sale_line_id.qty_transferred,
            timesheet.unit_amount,
            "The quantity delivered should be the quantity defined in the first timesheet of the task since the so_line in the second timesheet has manually been changed.",
        )

        self.task_rate_task.update(
            {
                "sale_line_id": self.so.line_ids[-1].id,
            }
        )
        timesheet._compute_so_line()
        edited_timesheet._compute_so_line()
        self.so.line_ids._compute_qty_transferred()

        self.assertEqual(
            timesheet.so_line,
            self.task_rate_task.sale_line_id,
            "SOL in timesheet should be the same than the one in the task.",
        )
        self.assertNotEqual(
            edited_timesheet.so_line,
            self.task_rate_task.sale_line_id,
            "SOL in timesheet which is manually edited should be different than the one in the task.",
        )
        self.assertEqual(
            edited_timesheet.so_line,
            self.so.line_ids[1],
            "SOL in timesheet should still be the same",
        )
