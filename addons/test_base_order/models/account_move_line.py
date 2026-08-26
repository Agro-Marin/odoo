from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    base_order_test_line_ids = fields.Many2many(
        comodel_name="base.order.test.line",
        relation="account_move_line_base_order_test_line_rel",
        column1="move_line_id",
        column2="order_line_id",
        string="Base Order Test Lines",
        copy=False,
    )

    def _get_fields_order_line_link(self):
        return [*super()._get_fields_order_line_link(), "base_order_test_line_ids"]
