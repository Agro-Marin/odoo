from odoo.tests import tagged

from odoo.addons.hr.tests.common import TestHrCommon


@tagged("-at_install", "post_install")
class TestHourlyCost(TestHrCommon):
    def test_hourly_cost_default_and_currency(self):
        employee = (
            self.env["hr.employee"]
            .with_user(self.res_users_hr_officer)
            .create({"name": "Hourly Cost Employee"})
        )
        self.assertEqual(employee.hourly_cost, 0.0)
        self.assertEqual(employee.currency_id, employee.company_id.currency_id)

        employee.with_user(self.res_users_hr_officer).hourly_cost = 42.0
        self.assertEqual(employee.hourly_cost, 42.0)
