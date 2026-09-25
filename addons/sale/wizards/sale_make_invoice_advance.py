from odoo import fields, models


class SaleAdvancePaymentInv(models.TransientModel):
    _name = "sale.advance.payment.inv"
    _inherit = ["mixin.order.advance.payment"]
    _description = "Sales Advance Payment Invoice"

    _order_field = "sale_order_ids"
    _invoice_order_path = "line_ids.sale_line_ids.order_id"

    count = fields.Count(
        count_of="sale_order_ids",
        string="Order Count",
    )
    sale_order_ids = fields.Many2many(
        comodel_name="sale.order",
        default=lambda self: self.env.context.get("active_ids"),
    )

    def _get_default_down_payment_account(self):
        return self.company_id.sale_config_id.downpayment_account_id
