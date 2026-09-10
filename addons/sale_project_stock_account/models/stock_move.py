from odoo import models
from odoo.fields import Domain


class StockMove(models.Model):
    _inherit = "stock.move"

    def _get_domain_valid_moves(self):
        domain = super()._get_domain_valid_moves()
        if self.env.user.company_id.anglo_saxon_accounting:
            domain = Domain.AND(
                [
                    domain,
                    [("product_id.expense_policy", "not in", ("sales_price", "cost"))],
                ]
            )
        return domain
