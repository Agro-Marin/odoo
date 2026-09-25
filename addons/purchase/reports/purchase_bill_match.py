from odoo import fields, models
from odoo.tools import frozendict

from odoo.addons.trade.tools import PURCHASE


class PurchaseBillMatch(models.Model):
    _name = "purchase.bill.match"
    _inherit = ["mixin.order.document.match"]
    _description = "Purchases & Bills Union"
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
            "purchase.order": [
                "amount_untaxed",
                "company_id",
                "currency_id",
                "date_order",
                "invoice_state",
                "name",
                "partner_id",
                "partner_ref",
                "state",
            ],
            "res.company": ["currency_id"],
        }
    )
    _rec_names_search = ["name", "reference"]
    _order = "date desc, name desc"

    _order_table = "purchase_order"
    _direction = PURCHASE

    move_id = fields.Many2one(
        comodel_name="account.move",
        string="Vendor Bill",
        readonly=True,
    )
    order_id = fields.Many2one(
        comodel_name="purchase.order",
        string="Purchase Order",
        readonly=True,
    )
