from itertools import batched

from odoo import api, models


class StockReplenishmentReport(models.AbstractModel):
    _inherit = "stock.replenishment.report"

    @api.model
    def _get_candidate_products(self):
        non_kit_ids = []
        for batch_ids in batched(
            super()._get_candidate_products().ids, 2000, strict=False
        ):
            products = self.env["product.product"].browse(batch_ids)
            kit_ids = {
                k.id
                for k in self.env["mrp.bom"]._bom_find(products, bom_type="phantom")
            }
            non_kit_ids.extend(id_ for id_ in products.ids if id_ not in kit_ids)
            products.invalidate_recordset()
        return self.env["product.product"].browse(non_kit_ids)
