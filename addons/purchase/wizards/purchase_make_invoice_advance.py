from odoo import fields, models


class PurchaseAdvancePaymentInv(models.TransientModel):
    _name = "purchase.advance.payment.inv"
    _inherit = ["mixin.order.advance.payment"]
    _description = "Purchase Advance Payment Bill"

    _order_field = "purchase_order_ids"
    _invoice_order_path = "line_ids.purchase_line_ids.order_id"

    advance_payment_method = fields.Selection(
        selection=[
            ("delivered", "Regular bill"),
            ("percentage", "Down payment (percentage)"),
            ("fixed", "Down payment (fixed amount)"),
        ],
        string="Create Bill",
        help="A standard bill is issued with all the order lines ready for billing, "
        "according to their billing policy (based on ordered or received quantity).",
    )
    count = fields.Count(
        count_of="purchase_order_ids",
        string="Order Count",
    )
    purchase_order_ids = fields.Many2many(
        comodel_name="purchase.order",
        default=lambda self: self.env.context.get("active_ids"),
    )

    def _get_draft_invoices_title(self):
        return self.env._("Draft Bills")

    def _get_down_payment_document_title(self):
        return self.env._("Down payment bill")
