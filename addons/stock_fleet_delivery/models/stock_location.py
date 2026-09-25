from odoo import fields, models

from .delivery_carrier import DISPATCH_MODES


class StockLocation(models.Model):
    _inherit = "stock.location"

    dispatch_mode = fields.Selection(
        selection=DISPATCH_MODES,
        help="How goods leaving from this location travel when their carrier does "
        "not say, e.g. the transit where third-party shipments wait for pickup.",
    )
