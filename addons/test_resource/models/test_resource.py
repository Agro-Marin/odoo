from odoo import fields, models


class ResourceTest(models.Model):
    _name = "resource.test"
    _description = "Test Resource Model"
    _inherit = ["mixin.resource"]

    name = fields.Char()
