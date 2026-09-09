from odoo.tests import tagged

from .common import TestCommonSaleTimesheet


@tagged("-at_install", "post_install")
class TestSoLineDeterminedInTimesheet(TestCommonSaleTimesheet):
    def test_sol_determined_when_project_is_task_rate(self):
        task = self.env["project.task"].create(
            {
                "name": "Task",
                "project_id": self.project_task_rate.id,
            }
        )

        self.assertEqual(
            task.sale_line_id,
            self.so.line_ids[-1],
            "The SOL in the task should be the one containing the prepaid service product.",
        )
        self.assertTrue(
            all(sol.qty_transferred == 0 for sol in self.so.line_ids),
            "The quantity delivered should be equal to 0 because we have no timesheet for each SOL containing in the SO.",
        )

        timesheet = self.env["account.analytic.line"].create(
            {
                "name": "Test Line",
                "unit_amount": 2,
                "employee_id": self.employee_manager.id,
                "project_id": self.project_task_rate.id,
                "task_id": task.id,
            }
        )
        self.assertEqual(
            timesheet.so_line,
            task.sale_line_id,
            "The SOL in the timesheet should be the same than the one in the task.",
        )
        self.assertEqual(
            self.so.line_ids[-1].qty_transferred,
            2,
            "The quantity delivered should be equal to 2.",
        )
        self.assertEqual(
            task.remaining_hours_so,
            0,
            "The remaining hours on the SOL containing the prepaid service product should be equals to 0.",
        )

        task2 = self.env["project.task"].create(
            {
                "name": "Task 2",
                "project_id": self.project_task_rate.id,
            }
        )
        self.assertFalse(
            task2.sale_line_id, "The SOL in this task should be equal to False"
        )

        task.update({"sale_line_id": self.so.line_ids[0].id})
        self.assertEqual(
            timesheet.so_line,
            task.sale_line_id,
            "The SOL in the timesheet should also change and be the same than the one in the task.",
        )

    def test_sol_determined_when_project_is_project_rate(self):
        self.project_project_rate = self.project_task_rate.copy(
            {
                "name": 'Project with pricing_type="project_rate"',
                "sale_line_id": self.so.line_ids[0].id,
            }
        )

        task = self.env["project.task"].create(
            {
                "name": "Task",
                "project_id": self.project_project_rate.id,
            }
        )
        self.assertEqual(
            task.sale_line_id,
            self.so.line_ids[0],
            "The SOL in the task should be the one containing the prepaid service product.",
        )
        self.assertTrue(
            all(sol.qty_transferred == 0 for sol in self.so.line_ids),
            "The quantity delivered should be equal to 0 because we have no timesheet for each SOL containing in the SO.",
        )

        timesheet = self.env["account.analytic.line"].create(
            {
                "name": "Test Line",
                "unit_amount": 1,
                "employee_id": self.employee_manager.id,
                "project_id": self.project_project_rate.id,
                "task_id": task.id,
            }
        )
        self.assertTrue(
            timesheet.so_line == task.sale_line_id == self.so.line_ids[0],
            "The SOL in the timesheet should be the same than the one in the task.",
        )
        self.assertEqual(
            self.so.line_ids[0].qty_transferred,
            1,
            "The quantity delivered should be equal to 1.",
        )

        task.update({"sale_line_id": self.so.line_ids[1].id})
        self.assertTrue(
            timesheet.so_line == task.sale_line_id == self.so.line_ids[1],
            "The SOL in the timesheet should also change and be the same than the one in the task.",
        )

    def test_sol_determined_when_project_is_employee_rate(self):
        self.project_employee_rate = self.project_task_rate.copy(
            {
                "name": 'Project with pricing_type="employee_rate"',
                "sale_line_id": self.so.line_ids[0].id,
                "sale_line_employee_ids": [
                    (
                        0,
                        0,
                        {
                            "employee_id": self.employee_user.id,
                            "sale_line_id": self.so.line_ids[1].id,
                        },
                    )
                ],
            }
        )
        mapping = self.project_employee_rate.sale_line_employee_ids

        task = self.env["project.task"].create(
            {
                "name": "Task",
                "project_id": self.project_employee_rate.id,
            }
        )
        self.assertEqual(
            task.sale_line_id,
            self.so.line_ids[0],
            "The SOL in the task should be the one containing the prepaid service product.",
        )
        self.assertTrue(
            all(sol.qty_transferred == 0 for sol in self.so.line_ids),
            "The quantity delivered should be equal to 0 because we have no timesheet for each SOL containing in the SO.",
        )

        timesheet = self.env["account.analytic.line"].create(
            {
                "name": "Test Line",
                "unit_amount": 1,
                "auto_account_id": self.analytic_account_sale.id,
                "employee_id": self.employee_manager.id,
                "project_id": self.project_employee_rate.id,
                "task_id": task.id,
            }
        )
        self.assertTrue(
            timesheet.so_line == task.sale_line_id == self.so.line_ids[0],
            "The SOL in the timesheet should be the same than the one in the task.",
        )
        self.assertEqual(
            self.so.line_ids[0].qty_transferred,
            1,
            "The quantity delivered should be equal to 1 for all SOLs in the SO.",
        )

        employee_user_timesheet = timesheet.copy(
            {
                "name": "Test Line Employee User",
                "employee_id": self.employee_user.id,
                "unit_amount": 2,
            }
        )
        employee_user_timesheet._compute_so_line()
        self.assertTrue(
            employee_user_timesheet.so_line
            == self.project_employee_rate.sale_line_employee_ids[0].sale_line_id
            == self.so.line_ids[1],
            "The SOL in the timesheet should be the one defined in the mapping for the employee user.",
        )
        self.assertEqual(
            self.so.line_ids[1].qty_transferred,
            2,
            "The quantity delivered for this SOL should be equal to 2 hours.",
        )

        task.update({"sale_line_id": self.so.line_ids[2].id})
        self.assertTrue(
            timesheet.so_line == task.sale_line_id == self.so.line_ids[2],
            "The SOL in the timesheet should also change and be the same than the one in the task.",
        )
        self.assertNotEqual(
            timesheet.so_line,
            employee_user_timesheet.so_line,
            "The SOL in the timesheet done by the employee user should not be the same than the one in the other timesheet in the task.",
        )

        mapping.update({"sale_line_id": self.so.line_ids[-1].id})
        self.assertTrue(
            employee_user_timesheet.so_line
            == mapping.sale_line_id
            == self.so.line_ids[-1],
            "The SOL in the timesheet done by the employee user should be the one defined in the mapping.",
        )
        self.assertNotEqual(
            timesheet.so_line,
            employee_user_timesheet.so_line,
            "The other timesheet should not have the SOL defined in the mapping.",
        )

    def test_no_so_line_if_project_non_billable(self):
        task = self.env["project.task"].create(
            {
                "name": "Test Task",
                "project_id": self.project_non_billable.id,
                "partner_id": self.partner_a.id,
            }
        )
        self.assertFalse(
            task.sale_line_id,
            "No SOL should be linked in this task because the project is non billable.",
        )

        timesheet = self.env["account.analytic.line"].create(
            {
                "name": "Test Line",
                "unit_amount": 1,
                "employee_id": self.employee_manager.id,
                "project_id": task.project_id.id,
                "task_id": task.id,
            }
        )
        self.assertFalse(
            timesheet.so_line,
            "No SOL should be linked in this timesheet because the project is non billable.",
        )

        timesheet1 = self.env["account.analytic.line"].create(
            {
                "name": "Test Line 1",
                "unit_amount": 1,
                "project_id": task.project_id.id,
                "employee_id": self.employee_manager.id,
            }
        )
        self.assertFalse(
            timesheet1.so_line,
            "This Timesheet is not billable since it has no task set and the project linked is not billable",
        )

    def test_tranfer_project(self):
        task = self.env["project.task"].create(
            {
                "name": "Test Task",
                "project_id": self.project_task_rate.id,
            }
        )

        self.assertEqual(
            task.sale_line_id,
            self.so.line_ids[-1],
            "The SOL with prepaid service product should be linked to the task.",
        )

        timesheet = self.env["account.analytic.line"].create(
            {
                "name": "Test Line",
                "unit_amount": 1,
                "employee_id": self.employee_manager.id,
                "project_id": task.project_id.id,
                "task_id": task.id,
            }
        )

        self.assertEqual(
            timesheet.so_line,
            task.sale_line_id,
            "The timesheet should have the same SOL than the task.",
        )

        task.write({"project_id": self.project_non_billable.id})

        self.assertFalse(
            timesheet.so_line,
            "No SOL should be linked to the timesheet because the project is non billable",
        )
