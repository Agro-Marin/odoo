from odoo import models


class TestTradeOrder(models.Model):
    _name = "test_trade.order"
    _inherit = ["test_trade.order", "mixin.order.invoice"]
