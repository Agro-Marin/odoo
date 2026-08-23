# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestExpensesTour(HttpCase):
    def test_tour_expenses(self):
        self.start_tour("/odoo", "hr_expense_test_tour", login="admin")
