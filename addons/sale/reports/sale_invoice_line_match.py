from odoo import fields, models
from odoo.tools import frozendict

from odoo.addons.trade.tools import SALE


class SaleInvoiceLineMatch(models.Model):
    _name = "sale.invoice.line.match"
    _inherit = ["mixin.order.line.match"]
    _description = "Sales Order Line & Customer Invoice Line Matching"
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
                "sale_line_ids",
            ],
            "sale.order": ["company_id", "currency_id", "state"],
            "sale.order.line": [
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

    _order_line_table = "sale_order_line"
    _order_table = "sale_order"
    _link_rel_table = "account_move_line_sale_order_line_rel"
    _link_field = "sale_line_ids"
    _direction = SALE
    _add_wizard_model = "invoice.to.so.wizard"
    _add_wizard_view = "sale.invoice_to_so_wizard_form"
    _add_order_context_key = "default_sale_order_id"

    order_line_id = fields.Many2one(
        comodel_name="sale.order.line",
        string="Sales Order Line",
        readonly=True,
    )
    order_id = fields.Many2one(
        comodel_name="sale.order",
        string="Sales Order",
        readonly=True,
    )

    def _get_no_order_line_message(self):
        return self.env._(
            "You must select at least one Sales Order line to match or create invoice."
        )

    def _get_add_to_order_messages(self):
        return {
            "no_invoice_line": self.env._(
                "Select Customer Invoice lines to add to a Sales Order"
            ),
            "multi_partner": self.env._(
                "Please select invoice lines with the same customer."
            ),
            "multi_order": self.env._(
                "Customer Invoice lines can only be added to one Sales Order."
            ),
            "action_name": self.env._("Add to Sales Order"),
        }

    def action_add_to_so(self):
        return self._action_add_to_order()
