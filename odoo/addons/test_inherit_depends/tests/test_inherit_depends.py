from odoo.tests import common


class TestInheritDepends(common.TransactionCase):
    def test_inherited_field_external_id(self):
        field = self.env["ir.model.fields"]._get("test_orm.foo", "published")
        self.assertTrue(field)
        self.assertEqual(
            field._get_external_ids(),
            {
                field.id: ["test_inherit_depends.field_test_orm_foo__published"],
            },
        )

    def test_40_selection_extension(self):
        mother = self.env["test.inherit.mother"]

        self.assertEqual(
            mother._fields["state"].selection,
            [
                ("a", "A"),
                ("d", "D"),
                ("b", "B"),
                ("c", "C"),
                ("e", "E"),
                ("g", "G"),
            ],
        )

    def test_60_inherit_with_python(self):
        self.assertEqual(self.env["test.inherit.mother"].foo(), 42 * 2)

    def test_50_field_extension_cross_module(self):
        mother = self.env["test.inherit.mother"]
        self.assertIn("field_in_mother_5", mother._fields)
