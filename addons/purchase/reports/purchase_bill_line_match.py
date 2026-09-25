from odoo import fields, models
from odoo.tools import frozendict

from odoo.addons.trade.tools import PURCHASE


class PurchaseBillLineMatch(models.Model):
    _name = "purchase.bill.line.match"
    _inherit = ["mixin.order.line.match"]
    _description = "Purchase Order Line & Vendor Bill Line Matching"
    _auto = False
    _depends = frozendict(
        {
            "account.move": ["move_type", "partner_id"],
            "account.move.line": [
                "amount_currency",
                "company_id",
                "currency_id",
                "display_type",
                "move_id",
                "parent_state",
                "product_id",
                "product_uom_id",
                "quantity",
                "purchase_line_ids",
            ],
            "purchase.order": ["company_id", "currency_id", "state"],
            "purchase.order.line": [
                "display_type",
                "is_downpayment",
                "order_id",
                "partner_id",
                "price_subtotal",
                "product_id",
                "product_qty",
                "product_uom_id",
                "qty_invoiced",
                "qty_to_invoice",
            ],
        }
    )
    _order = "product_id, aml_id, order_line_id"

    _order_line_table = "purchase_order_line"
    _order_table = "purchase_order"
    _link_rel_table = "account_move_line_purchase_order_line_rel"
    _link_field = "purchase_line_ids"
    _direction = PURCHASE
    _add_wizard_model = "bill.to.po.wizard"
    _add_wizard_view = "purchase.bill_to_po_wizard_form"
    _add_order_context_key = "default_purchase_order_id"

    order_line_id = fields.Many2one(
        comodel_name="purchase.order.line",
        string="Purchase Order Line",
        readonly=True,
    )
    order_id = fields.Many2one(
        comodel_name="purchase.order",
        string="Purchase Order",
        readonly=True,
    )

    def _get_no_order_line_message(self):
        return self.env._(
            "You must select at least one Purchase Order line to match or create bill."
        )

    def _get_add_to_order_messages(self):
        return {
            "no_invoice_line": self.env._(
                "Select Vendor Bill lines to add to a Purchase Order"
            ),
            "multi_partner": self.env._(
                "Please select bill lines with the same vendor."
            ),
            "multi_order": self.env._(
                "Vendor Bill lines can only be added to one Purchase Order."
            ),
            "action_name": self.env._("Add to Purchase Order"),
        }

    def action_add_to_po(self):
        return self._action_add_to_order()
