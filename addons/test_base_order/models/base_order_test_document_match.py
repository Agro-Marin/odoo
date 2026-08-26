from odoo import fields, models


class BaseOrderTestDocumentMatch(models.Model):
    """Concrete `mixin.order.document.match`, so the union is testable.

    The mixin builds a SQL view putting posted invoices and confirmed,
    not-yet-fully-invoiced orders side by side, so somebody reconciling the two
    sees one list. Both shipping models live in `sale` and `purchase`.
    """

    _name = "base.order.test.document.match"
    _inherit = ["mixin.order.document.match"]
    _description = "Base Order Test & Invoices Union"
    _auto = False
    _rec_names_search = ["name", "reference"]
    _order = "date desc, name desc"

    _order_table = "base_order_test"
    _move_types = ("out_invoice", "out_refund")
    _order_reference_column = "partner_ref"

    move_id = fields.Many2one(
        comodel_name="account.move",
        string="Invoice",
        readonly=True,
    )
    order_id = fields.Many2one(
        comodel_name="base.order.test",
        string="Base Order Test",
        readonly=True,
    )
