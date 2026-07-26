from odoo import fields, models


class TestUnit(models.Model):
    _inherit = "test.unit"

    second_name = fields.Char()
