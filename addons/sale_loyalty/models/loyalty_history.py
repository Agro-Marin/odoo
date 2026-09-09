from odoo import models


class LoyaltyHistory(models.Model):
    _inherit = "loyalty.history"

    def _compute_order_portal_url(self):
        sale_lines = self.filtered(
            lambda line: line.order_model == "sale.order" and line.order_id
        )
        super(LoyaltyHistory, self - sale_lines)._compute_order_portal_url()
        orders = self.env["sale.order"].browse(sale_lines.mapped("order_id")).exists()
        urls = {order.id: order.get_portal_url() for order in orders}
        for line in sale_lines:
            line.order_portal_url = urls.get(line.order_id, False)
