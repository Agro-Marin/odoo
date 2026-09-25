from odoo import fields, models


class TradeConfig(models.Model):
    _inherit = "trade.config"

    test_trade_order_lock = fields.Selection(
        selection=[
            ("edit", "Allow to edit test orders"),
            ("lock", "Confirmed test orders are not editable"),
        ],
        default="edit",
    )
