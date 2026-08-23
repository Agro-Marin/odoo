from odoo import api, fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    purchase_line_ids = fields.Many2many(
        comodel_name="purchase.order.line",
        relation="account_move_line_purchase_order_line_rel",
        column1="move_line_id",
        column2="order_line_id",
        string="Purchase Order Lines",
        copy=False,
    )
    purchase_line_warn_msg = fields.Text(
        compute="_compute_purchase_line_warn_msg",
    )

    @api.depends("product_id.purchase_line_warn_msg")
    def _compute_purchase_line_warn_msg(self):
        self._compute_warn_msg_from_product(
            "purchase_line_warn_msg",
            "purchase.group_warning_purchase",
        )

    def _get_fields_order_line_link(self):
        return [*super()._get_fields_order_line_link(), "purchase_line_ids"]

    def _purchase_prepare_purchase_line_values(self):
        return [
            {
                "product_id": line.product_id.id,
                "product_qty": line.quantity,
                "product_uom_id": line.product_uom_id.id,
                "price_unit": line.price_unit,
                "discount": line.discount,
            }
            for line in self
        ]
