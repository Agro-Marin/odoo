from odoo.tests import TransactionCase


class TestProjectTimesheetProductOnCreate(TransactionCase):
    def test_a_project_that_is_not_billable_has_no_timesheet_product(self):
        project = self.env["project.project"].create(
            {"name": "Internal", "allow_billable": False}
        )

        self.assertFalse(project.timesheet_product_id)

    def test_a_billable_project_with_timesheets_gets_the_time_product(self):
        project = self.env["project.project"].create(
            {"name": "Billable", "allow_billable": True, "allow_timesheets": True}
        )

        self.assertEqual(
            project.timesheet_product_id, self.env.ref("sale_timesheet.time_product")
        )
