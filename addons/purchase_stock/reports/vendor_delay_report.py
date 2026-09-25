from odoo import fields, models

from odoo.addons.trade.tools import PURCHASE


class VendorDelayReport(models.Model):
    _name = "vendor.delay.report"
    _inherit = ["mixin.order.delay.report"]
    _description = "Vendor Delay Report"
    _auto = False

    _order_line_table = "purchase_order_line"
    _order_table = "purchase_order"
    _link_column = "purchase_line_id"
    _date_commitment_alias = "ol"
    _direction = PURCHASE

    partner_id = fields.Many2one(string="Vendor")
