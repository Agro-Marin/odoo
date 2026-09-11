from odoo import fields, models


class SaleInvoiceMatch(models.Model):
    _name = "sale.invoice.match"
    _inherit = ["mixin.order.document.match"]
    _description = "Sales & Invoices Union"
    _auto = False
    _rec_names_search = ["name", "reference"]
    _order = "date desc, name desc"

    _order_table = "sale_order"
    _move_types = ("out_invoice", "out_refund")
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
