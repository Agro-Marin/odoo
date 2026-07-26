from odoo import fields, models


class TestInheritMother(models.Model):
    _inherit = "test.inherit.mother"

    state = fields.Selection(selection_add=[("d", "D"), ("b",)])
    field_in_mother_3 = fields.Char()
