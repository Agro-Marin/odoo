from odoo import api, fields, models


class Test_Inherit_Daughter(models.Model):
    _name = "test_inherit_daughter"
    _description = "Test Inherit Daughter"
    _inherits = {"test.inherit.mother": "template_id"}

    template_id = fields.Many2one(
        "test.inherit.mother",
        "Template",
        delegate=True,
        required=True,
        ondelete="cascade",
    )
    field_in_daughter = fields.Char("Field1")


class Test_Inherit_Daughter(models.Model):
    _inherit = "test_inherit_daughter"

    template_id = fields.Many2one()

    name = fields.Char(default="Baz")


class ResPartner(models.Model):
    _inherit = "res.partner"

    daughter_ids = fields.One2many(
        "test_inherit_daughter", "partner_id", string="My daughter_ids"
    )


class Test_Inherit_Property(models.Model):
    _name = "test_inherit_property"
    _description = "Test Inherit Property"

    name = fields.Char("Name", required=True)
    property_foo = fields.Integer(string="Foo", company_dependent=True)
    property_bar = fields.Integer(string="Bar", company_dependent=True)


class Test_Inherit_Property(models.Model):
    _inherit = "test_inherit_property"

    property_foo = fields.Integer(company_dependent=False)

    property_bar = fields.Integer(compute="_compute_bar", company_dependent=False)

    def _compute_bar(self):
        for record in self:
            record.property_bar = 42


class Test_Inherit_Parent(models.AbstractModel):
    _name = "test_inherit_parent"
    _description = "Test Inherit Parent"

    def stuff(self):
        return "P1"


class Test_Inherit_Child(models.AbstractModel):
    _name = "test_inherit_child"
    _inherit = ["test_inherit_parent"]
    _description = "Test Inherit Child"

    bar = fields.Integer()

    def stuff(self):
        return super().stuff() + "C1"


class Test_Inherit_Parent(models.AbstractModel):
    _inherit = "test_inherit_parent"

    foo = fields.Integer()

    _unique_foo = models.Constraint(
        "UNIQUE(foo)",
        "foo must be unique",
    )

    def stuff(self):
        return super().stuff() + "P2"

    @api.constrains("foo")
    def _check_foo(self):
        pass


class TestOrmSelection(models.Model):
    _inherit = "test_orm.selection"

    state = fields.Selection(selection_add=[("bar", "Bar"), ("baz", "Baz")])
    other = fields.Selection("_other_values")

    def _other_values(self):
        return [("baz", "Baz")]


class MixinTest_Inherit_(models.AbstractModel):
    _name = "mixin.test_inherit"
    _description = "Test Inherit Mixin"

    published = fields.Boolean()


class TestOrmMessage(models.Model):
    _inherit = "test_orm.message"

    body = fields.Text(translate=True)
