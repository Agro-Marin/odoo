from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    vehicle_service = fields.Boolean()
