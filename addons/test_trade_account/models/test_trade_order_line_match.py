from odoo import fields, models
from odoo.tools import frozendict

from odoo.addons.trade.tools import SALE


class TestTradeOrderLineMatch(models.Model):
    """Concrete `mixin.order.line.match`, so its matching algorithm is testable.

    The mixin builds a SQL view unioning open order lines with unlinked
    invoice lines, and `action_match_lines` writes the links between them.
    Every shipping model that carries it lives in `sale` or `purchase`, so
    until this existed the algorithm ran in production and was asserted by
    nothing.
    """

    _name = "test_trade.order.line.match"
    _inherit = ["mixin.order.line.match"]
    _description = "Base Order Test Line & Invoice Line Matching"
    _auto = False
    _depends = frozendict(
        {
            "account.move": ["move_type", "partner_id"],
            "account.move.line": [
                "amount_currency",
                "company_id",
                "currency_id",
                "display_type",
                "move_id",
                "parent_state",
                "product_id",
                "product_uom_id",
                "quantity",
                "test_trade_order_line_ids",
            ],
            "test_trade.order": ["company_id", "currency_id", "state"],
            "test_trade.order.line": [
                "display_type",
                "is_downpayment",
                "order_id",
                "partner_id",
                "price_subtotal",
                "product_id",
                "product_qty",
                "product_uom_id",
                "qty_invoiced",
                "qty_to_invoice",
            ],
        }
    )
    _order = "product_id, aml_id, order_line_id"

    _order_line_table = "test_trade_order_line"
    _order_table = "test_trade_order"
    _link_rel_table = "account_move_line_test_trade_order_line_rel"
    _link_field = "test_trade_order_line_ids"
    _direction = SALE

    order_line_id = fields.Many2one(
        comodel_name="test_trade.order.line",
        string="Base Order Test Line",
        readonly=True,
    )
    order_id = fields.Many2one(
        comodel_name="test_trade.order",
        string="Base Order Test",
        readonly=True,
    )
