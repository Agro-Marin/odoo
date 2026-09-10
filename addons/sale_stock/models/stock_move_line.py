from odoo import models


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    def _get_counterparty_usages(self):
        return super()._get_counterparty_usages() | {"customer"}
