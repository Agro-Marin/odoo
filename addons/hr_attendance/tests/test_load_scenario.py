from odoo.tests.common import TransactionCase


class TestHrAttendanceScenario(TransactionCase):
    def test_load_scenario(self):
        self.env["hr.attendance"]._load_demo_data()

        employees = self.env["hr.employee"].browse(
            [
                self.env.ref("hr.employee_sj").id,
                self.env.ref("hr.employee_mw").id,
                self.env.ref("hr.employee_eg").id,
            ]
        )
        for employee in employees:
            self.assertTrue(
                employee.attendance_ids,
                f"{employee.name} should have demo attendance records",
            )
