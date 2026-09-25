from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    test_trade_order_line_ids = fields.Many2many(
        comodel_name="test_trade.order.line",
        relation="account_move_line_test_trade_order_line_rel",
        column1="move_line_id",
        column2="order_line_id",
        string="Base Order Test Lines",
        copy=False,
    )

    def _get_fields_order_line_link(self):
        return [*super()._get_fields_order_line_link(), "test_trade_order_line_ids"]
