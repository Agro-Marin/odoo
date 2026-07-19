from odoo import fields, models


class TestInheritMother(models.Model):
    _inherit = "test.inherit.mother"

    # extend again the selection of the state field
    state = fields.Selection(selection_add=[("e", "E")])
    field_in_mother_4 = fields.Char()

    def foo(self):
        return self.bar()
