from odoo import fields, models


class AccountMoveLine(models.Model):
    """Override AccountMoveLine to add the link to the purchase order line it is related to"""

    _inherit = "account.move.line"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    is_downpayment = fields.Boolean()
    purchase_line_ids = fields.Many2many(
        comodel_name="purchase.order.line",
        relation="account_move_line_purchase_order_line_rel",
        column1="move_line_id",
        column2="order_line_id",
        string="Purchases Order Lines",
        readonly=True,
        copy=False,
    )

    # -------------------------------------------------------------------------
    # HELPER
    # -------------------------------------------------------------------------

    def _copy_data_extend_business_fields(self, values):
        super()._copy_data_extend_business_fields(values)
        values["purchase_line_ids"] = [(6, None, self.purchase_line_ids.ids)]

    def _prepare_purchase_line_vals(self):
        return [
            {
                "product_id": line.product_id.id,
                "product_uom_id": line.product_uom_id.id,
                "product_qty": line.quantity,
                "price_unit": line.price_unit,
                "discount": line.discount,
            }
            for line in self
        ]
