from odoo import fields, models
from odoo.tools import frozendict

from odoo.addons.trade.tools import PURCHASE


class VendorDelayReport(models.Model):
    _name = "vendor.delay.report"
    _inherit = ["mixin.order.delay.report"]
    _description = "Vendor Delay Report"
    _auto = False
    _depends = frozendict(
        {
            "product.product": ["product_tmpl_id"],
            "product.template": ["categ_id", "uom_id"],
            "purchase.order": ["company_id"],
            "purchase.order.line": [
                "date_commitment",
                "order_id",
                "partner_id",
                "product_id",
                "product_uom_qty",
            ],
            "stock.location": ["parent_path", "usage"],
            "stock.move": [
                "date",
                "location_id",
                "product_id",
                "purchase_line_id",
                "state",
            ],
            "stock.move.line": ["move_id", "product_uom_id", "quantity"],
            "uom.uom": ["factor"],
        }
    )

    _order_line_table = "purchase_order_line"
    _order_table = "purchase_order"
    _link_column = "purchase_line_id"
    _date_commitment_alias = "ol"
    _direction = PURCHASE
    _access_anchors = frozendict(
        {
            "company": models.Anchor("company_id", shared=False),
        }
    )

    partner_id = fields.Many2one(string="Vendor")
