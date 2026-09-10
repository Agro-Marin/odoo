from odoo import models


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    def _is_lot_display_in_invoice_required(self):
        return (
            super()._is_lot_display_in_invoice_required()
            or bool(
                self._get_counterparty_usages()
                & {self.location_id.usage, self.location_dest_id.usage},
            )
            or self.env.ref("stock.stock_location_inter_company")
            in (
                self.location_id,
                self.location_dest_id,
            )
        )

    def _get_counterparty_usages(self):
        return set()
