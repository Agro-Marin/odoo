import re
from pathlib import Path

from lxml import etree

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


class TestDeclaredCategoriesStayUpdatable(TransactionCase):
    """The 1.42 pre-migration carries a list, and a list goes stale in silence.

    `get_or_create_category_id` inserts every row `noupdate = True`, so on an
    upgraded database a data file can no longer correct a category it declares
    -- not its name, not its sequence, not its parent. `base/migrations/1.42/
    pre-migrate_declared_categories_are_updatable.py` clears the flag for the
    rows base speaks for, and it has to name them one by one: clearing it for
    the model would hand every auto-created category to `_process_end`, which
    reaps exactly the rows that are absent from `loaded_xmlids` and not
    `noupdate`.

    So a record added to the data file and not to that list is a record the
    data file will go on being unable to correct, on every database that has
    already been upgraded past 1.42 -- and nothing about that is visible at
    the point the record is written.
    """

    BASE = Path(__file__).resolve().parents[1]

    def _declared_in_data(self):
        tree = etree.parse(str(self.BASE / "data" / "ir_module_category_data.xml"))
        return {
            record.get("id").split(".")[-1]
            for record in tree.getroot().iter("record")
            if record.get("model") == "ir.module.category"
        }

    def _named_in_the_migration(self):
        source = (
            self.BASE
            / "migrations"
            / "1.42"
            / "pre-migrate_declared_categories_are_updatable.py"
        ).read_text()
        return set(re.findall(r'"(module_category_[a-z0-9_()]+)"', source))

    def test_every_declared_category_is_named_in_the_migration(self):
        declared = self._declared_in_data()
        self.assertTrue(declared, "the data file parsed to no category at all")
        self.assertEqual(
            sorted(declared - self._named_in_the_migration()),
            [],
            "these categories are declared in base's data file but absent from "
            "the 1.42 pre-migration, so an upgraded database keeps them "
            "noupdate and the data file cannot correct them",
        )

    def test_the_migration_names_nothing_the_data_file_does_not_declare(self):
        # The other direction is the cheaper mistake and the one that rots: a
        # name left behind after its record is removed clears noupdate on a row
        # no data file speaks for, which is the one case `_process_end` reaps.
        self.assertEqual(
            sorted(self._named_in_the_migration() - self._declared_in_data()),
            [],
            "the 1.42 pre-migration names categories base's data file does not "
            "declare; clearing noupdate on a row no data file owns makes it "
            "reapable",
        )
