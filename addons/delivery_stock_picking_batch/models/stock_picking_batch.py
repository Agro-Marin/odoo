from odoo import models


class StockPickingBatch(models.Model):
    _inherit = "stock.picking.batch"

    def _is_auto_mergeable(self, *, moves=0, pickings=0, weight=0.0):
        if not super()._is_auto_mergeable(
            moves=moves, pickings=pickings, weight=weight
        ):
            return False
        max_weight = self.picking_type_id.batch_max_weight
        return not (
            weight
            and max_weight
            and sum(self.picking_ids.mapped("weight")) + weight > max_weight
        )
