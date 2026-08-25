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


class TestUpdateCategoryIdentity(TransactionCase):
    """`_update_category` must settle, whatever the resolved category is *named*.

    `create_categories` keys a category by an xml_id derived from the manifest
    path, and base data is free to name that record anything: the manifest path
    `Accounting/Accounting` is stored under the name `Invoicing`. Comparing the
    path against the stored display names therefore never matched for such a
    category, so every `update_list()` re-resolved it and rewrote `category_id`
    to the value it already held -- for 630 of this workspace's 1556 modules.
    """

    def _module(self, suffix=""):
        return self.env["ir.module.module"].create(
            {"name": f"test_update_category_module{suffix}", "state": "uninstalled"}
        )

    def test_a_renamed_category_settles_after_one_pass(self):
        module = self._module()
        module._update_category("Accounting/Accounting")
        self.env.flush_all()
        category = module.category_id
        self.assertTrue(category, "the manifest path must resolve to a category")
        self.assertNotEqual(
            category.name,
            "Accounting",
            "vacuous unless base data renames that category away from its path",
        )

        writes = []
        original_write = type(module).write

        def spy(records, vals):
            writes.append(vals)
            return original_write(records, vals)

        self.patch(type(module), "write", spy)
        for _ in range(3):
            module._update_category("Accounting/Accounting")
        self.env.flush_all()

        self.assertEqual(
            writes, [], "a category already at its manifest path must not be rewritten"
        )
        self.assertEqual(module.category_id, category)

    def test_a_changed_path_still_moves_the_module(self):
        module = self._module()
        module._update_category("Accounting/Accounting")
        self.env.flush_all()
        first = module.category_id

        module._update_category("Sales")
        self.env.flush_all()
        self.assertTrue(module.category_id)
        self.assertNotEqual(
            module.category_id, first, "a different path must still move the module"
        )

    def test_the_cache_and_the_database_agree(self):
        module = self._module()
        cached = {}
        module._update_category("Accounting/Accounting", cached)
        with_cache = module.category_id.id

        other = self._module("_other")
        other._update_category("Accounting/Accounting")
        self.assertEqual(
            other.category_id.id,
            with_cache,
            "resolving with and without a cache must land on the same category",
        )
