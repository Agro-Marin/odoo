from odoo import models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def _prepare_picking_vals(self):
        res = super()._prepare_picking_vals()
        if not self.project_id:
            return res
        return {
            **res,
            "project_id": self.project_id.id,
        }
