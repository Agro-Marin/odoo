from odoo import fields, models


class PurchaseOrderDiscount(models.TransientModel):
    _name = "purchase.order.discount"
    _inherit = ["mixin.order.discount"]
    _description = "Purchase Discount Wizard"

    _order_field = "purchase_order_id"

    purchase_order_id = fields.Many2one(
        comodel_name="purchase.order",
        default=lambda self: self.env.context.get("active_id"),
        required=True,
    )
    company_id = fields.Many2one(related="purchase_order_id.company_id")
    currency_id = fields.Many2one(related="purchase_order_id.currency_id")

    def _get_discount_product_config(self):
        return self.company_id.purchase_config_id, "purchase_discount_product_id"
