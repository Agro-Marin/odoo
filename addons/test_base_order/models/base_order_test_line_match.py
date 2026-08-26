from odoo import fields, models


class BaseOrderTestLineMatch(models.Model):
    """Concrete `mixin.order.line.match`, so its matching algorithm is testable.

    The mixin builds a SQL view unioning open order lines with unlinked
    invoice lines, and `action_match_lines` writes the links between them.
    Every shipping model that carries it lives in `sale` or `purchase`, so
    until this existed the algorithm ran in production and was asserted by
    nothing.
    """

    _name = "base.order.test.line.match"
    _inherit = ["mixin.order.line.match"]
    _description = "Base Order Test Line & Invoice Line Matching"
    _auto = False
    _order = "product_id, aml_id, order_line_id"

    _order_line_table = "base_order_test_line"
    _order_table = "base_order_test"
    _link_rel_table = "account_move_line_base_order_test_line_rel"
    _link_field = "base_order_test_line_ids"
    _move_types = ("out_invoice", "out_refund")

    order_line_id = fields.Many2one(
        comodel_name="base.order.test.line",
        string="Base Order Test Line",
        readonly=True,
    )
    order_id = fields.Many2one(
        comodel_name="base.order.test",
        string="Base Order Test",
        readonly=True,
    )
