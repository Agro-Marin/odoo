from odoo import fields, models
from odoo.tools import frozendict

from odoo.addons.trade.tools import SALE


class TestTradeOrderDocumentMatch(models.Model):
    """Concrete `mixin.order.document.match`, so the union is testable.

    The mixin builds a SQL view putting posted invoices and confirmed,
    not-yet-fully-invoiced orders side by side, so somebody reconciling the two
    sees one list. Both shipping models live in `sale` and `purchase`.
    """

    _name = "test_trade.order.document.match"
    _inherit = ["mixin.order.document.match"]
    _description = "Base Order Test & Invoices Union"
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
            "test_trade.order": [
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
        }
    )
    _rec_names_search = ["name", "reference"]
    _order = "date desc, name desc"

    _order_table = "test_trade_order"
    _direction = SALE
    _order_reference_column = "partner_ref"

    move_id = fields.Many2one(
        comodel_name="account.move",
        string="Invoice",
        readonly=True,
    )
    order_id = fields.Many2one(
        comodel_name="test_trade.order",
        string="Base Order Test",
        readonly=True,
    )
