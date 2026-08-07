from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestModuleCategory(TransactionCase):
    def test_parent_circular_dependencies(self):
        Cats = self.env["ir.module.category"]

        def create(name, **kw):
            return Cats.create(dict(kw, name=name))

        category_a = create("A", parent_id=False)
        category_b = create("B", parent_id=category_a.id)
        category_c = create("C", parent_id=category_b.id)

        with self.assertRaises(ValidationError):
            category_a.write({"parent_id": category_c.id})
        with self.assertRaises(ValidationError):
            category_b.write({"parent_id": category_b.id})

    def test_write_invalidates_group_hierarchy_cache(self):
        Groups = self.env["res.groups"]
        category = self.env["ir.module.category"].search(
            [("privilege_ids.group_ids", "!=", False)], limit=1
        )
        self.assertTrue(category, "no category with privileges to exercise")

        def hierarchy_entry():
            return next(
                entry
                for entry in Groups._get_view_group_hierarchy()["categories"]
                if entry["id"] == category.id
            )

        self.assertEqual(hierarchy_entry()["name"], category.name)

        category.write({"name": "Renamed Application"})
        self.env.flush_all()
        self.assertEqual(hierarchy_entry()["name"], "Renamed Application")
