# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class StockLocation(models.Model):
    _inherit = "stock.location"


    is_a_dock = fields.Boolean("Is a Dock Location")
