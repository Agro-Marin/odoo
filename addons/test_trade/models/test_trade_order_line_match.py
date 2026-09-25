from odoo import fields, models


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
    _order = "product_id, aml_id, order_line_id"

    _order_line_table = "test_trade_order_line"
    _order_table = "test_trade_order"
    _link_rel_table = "account_move_line_test_trade_order_line_rel"
    _link_field = "test_trade_order_line_ids"
    _move_types = ("out_invoice", "out_refund")

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
