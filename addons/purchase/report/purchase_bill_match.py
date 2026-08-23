from odoo import fields, models


class PurchaseBillMatch(models.Model):
    _name = "purchase.bill.match"
    _inherit = ["mixin.order.document.match"]
    _description = "Purchases & Bills Union"
    _auto = False
    _rec_names_search = ["name", "reference"]
    _order = "date desc, name desc"

    _order_table = "purchase_order"
    _move_types = ("in_invoice", "in_refund")

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
