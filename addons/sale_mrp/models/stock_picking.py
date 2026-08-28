from odoo import api, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    @api.depends(
        "reference_ids.sale_ids",
        "reference_ids.production_ids",
        "move_ids.sale_line_id.order_id",
    )
    def _compute_sale_id(self):
        return super()._compute_sale_id()

    def _is_on_manufacturing_route(self):
        self.ensure_one()
        return bool(self.reference_ids.production_ids)
