from collections import defaultdict

from odoo import api, models


class MixinOrderLineTransfer(models.AbstractModel):
    _name = "mixin.order.line.transfer"
    _description = "Order Line Transferred Quantity"

    @api.depends("qty_transferred_method")
    def _compute_qty_transferred(self):
        lines_manual = self.filtered(
            lambda line: line.qty_transferred_method == "manual",
        )
        lines_manual.qty_transferred = 0.0

    def _prepare_qty_transferred(self):
        transferred_qties = defaultdict(float)
        for line in self:
            if line.qty_transferred_method == "manual":
                transferred_qties[line] = line.qty_transferred or 0.0
            else:
                transferred_qties[line] = 0.0
        return transferred_qties
