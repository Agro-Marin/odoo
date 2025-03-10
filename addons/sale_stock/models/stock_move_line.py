from odoo import models


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    def _should_show_lot_in_invoice(self):
        return "customer" in {self.location_id.usage, self.location_dest_id.usage}
