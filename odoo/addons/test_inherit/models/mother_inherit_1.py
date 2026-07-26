from odoo import fields, models


class TestInheritMother(models.Model):
    _inherit = "test.inherit.mother"

    field_in_mother = fields.Char()
    partner_id = fields.Many2one("res.partner")
    state = fields.Selection([("a", "A"), ("b", "B")], default="a")

    name = fields.Char(required=True, default="Bar")

    def bar(self):
        return 42


class Test_Mother_Underscore(models.Model):
    _name = "test_mother_underscore"
    _description = "Test Inherit Underscore"
    _inherit = ["test.inherit.mother"]


class Test_Mother_Underscore(models.Model):
    _inherit = "test_mother_underscore"

    foo = fields.Char()
