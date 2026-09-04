from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import CommonPosTest


@tagged("post_install", "-at_install")
class TestPosHrLoggedCashiers(CommonPosTest):
    def test_session_remembers_every_cashier_that_logged_in(self):
        """`employee_id` only ever holds whoever is at the register now, so on
        its own it cannot answer who worked the shift."""
        self.pos_config_usd.open_ui()
        session = self.pos_config_usd.current_session_id
        ana = self.env["hr.employee"].sudo().create({"name": "Ana"})
        beto = self.env["hr.employee"].sudo().create({"name": "Beto"})

        session.employee_id = ana
        session.employee_id = beto

        self.assertEqual(session.employee_id, beto)
        self.assertEqual(session.logged_employee_ids, ana | beto)

    def test_a_cashier_logging_in_twice_is_listed_once(self):
        self.pos_config_usd.open_ui()
        session = self.pos_config_usd.current_session_id
        ana = self.env["hr.employee"].sudo().create({"name": "Ana"})
        beto = self.env["hr.employee"].sudo().create({"name": "Beto"})

        session.employee_id = ana
        session.employee_id = beto
        session.employee_id = ana

        self.assertEqual(session.logged_employee_ids, ana | beto)
