from odoo import models


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    def _counterparty_usages(self):
        return super()._counterparty_usages() | {"supplier"}
