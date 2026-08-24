from odoo import models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def _get_discount_lines(self):
        lines = super()._get_discount_lines()
        lines |= self.filtered(
            lambda line: any(sl._is_discount_line() for sl in line.sale_line_ids)
        )
        return lines
