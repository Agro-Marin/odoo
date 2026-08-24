from odoo import models


class ProductTag(models.Model):
    _name = "product.tag"
    _inherit = ["mixin.website.multi", "product.tag"]
