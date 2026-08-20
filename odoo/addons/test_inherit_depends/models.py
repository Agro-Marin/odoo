from odoo import fields, models


class TestOrmFoo(models.Model):
    _name = "test_orm.foo"
    _inherit = ["test_orm.foo", "mixin.test_inherit"]


class TestInheritMother(models.Model):
    _inherit = "test.inherit.mother"

    state = fields.Selection(selection_add=[("g", "G")])
    field_in_mother_5 = fields.Char()

    def foo(self):
        return super().foo() * 2
