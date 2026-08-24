from odoo.tests.common import TransactionCase


class TestHrAttendanceScenario(TransactionCase):
    def test_load_scenario(self):
        self.env["hr.attendance"]._load_demo_data()
