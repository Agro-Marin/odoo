from odoo import models


class AccountMove(models.Model):
    _inherit = "account.move"

    def _reverse_moves(self, default_values_list=None, cancel=False):
        self.expense_ids._sale_expense_reset_sol_quantities()
        return super()._reverse_moves(default_values_list, cancel)

    def action_draft(self):
        self.expense_ids._sale_expense_reset_sol_quantities()
        return super().action_draft()

    def unlink(self):
        self.expense_ids._sale_expense_reset_sol_quantities()
        return super().unlink()
