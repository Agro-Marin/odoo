from odoo import models


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    def _action_launch_stock_rule(self, **kwargs):
        gelato_lines = self.filtered(lambda l: l.product_id.gelato_product_uid)
        super(SaleOrderLine, self - gelato_lines)._action_launch_stock_rule(**kwargs)
