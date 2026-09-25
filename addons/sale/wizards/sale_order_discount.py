from odoo import fields, models


class SaleOrderDiscount(models.TransientModel):
    _name = "sale.order.discount"
    _inherit = ["mixin.order.discount"]
    _description = "Discount Wizard"

    _order_field = "sale_order_id"

    sale_order_id = fields.Many2one(
        comodel_name="sale.order",
        default=lambda self: self.env.context.get("active_id"),
        required=True,
    )
    company_id = fields.Many2one(related="sale_order_id.company_id")
    currency_id = fields.Many2one(related="sale_order_id.currency_id")

    def _get_discount_product_config(self):
        return self.company_id.sale_config_id, "sale_discount_product_id"
