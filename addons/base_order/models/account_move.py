from odoo import models


class AccountMove(models.Model):
    _inherit = "account.move"

    def _add_order_lines(self, order_lines):
        if not order_lines:
            return
        self.ensure_one()
        order_lines._assert_invoiced_uom_convertible()
        new_line_ids = self.env["account.move.line"]

        for order_line in order_lines:
            new_line_values = order_line._prepare_aml_vals(move=self)
            new_line_ids += self.env["account.move.line"].new(new_line_values)

        self.invoice_line_ids += new_line_ids
