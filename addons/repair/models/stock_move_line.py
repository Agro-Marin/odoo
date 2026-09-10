from odoo import models


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    def _is_lot_display_in_invoice_required(self):
        return (
            super()._is_lot_display_in_invoice_required()
            or self.move_id.repair_line_type
        )
