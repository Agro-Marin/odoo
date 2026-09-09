from odoo import api, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    @api.depends("reference_ids", "reference_ids.purchase_ids")
    def _compute_purchase_order_count(self):
        super()._compute_purchase_order_count()

    def _get_purchase_orders(self):
        return super()._get_purchase_orders() | self.reference_ids.purchase_ids
