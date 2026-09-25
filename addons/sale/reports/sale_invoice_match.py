from odoo import fields, models
from odoo.tools import frozendict

from odoo.addons.trade.tools import SALE


class SaleInvoiceMatch(models.Model):
    _name = "sale.invoice.match"
    _inherit = ["mixin.order.document.match"]
    _description = "Sales & Invoices Union"
    _auto = False
    _depends = frozendict(
        {
            "account.move": [
                "amount_untaxed",
                "company_id",
                "currency_id",
                "date",
                "move_type",
                "name",
                "partner_id",
                "ref",
                "state",
            ],
            "sale.order": [
                "amount_untaxed",
                "client_order_ref",
                "company_id",
                "currency_id",
                "date_order",
                "invoice_state",
                "name",
                "partner_id",
                "state",
            ],
        }
    )
    _rec_names_search = ["name", "reference"]
    _order = "date desc, name desc"

    _order_table = "sale_order"
    _direction = SALE
    _order_reference_column = "client_order_ref"

    move_id = fields.Many2one(
        comodel_name="account.move",
        string="Customer Invoice",
        readonly=True,
    )
    order_id = fields.Many2one(
        comodel_name="sale.order",
        string="Sales Order",
        readonly=True,
    )
