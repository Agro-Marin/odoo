from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.tests.common import TransactionCase


class TestMapped(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Category = cls.env["test_orm.category"]
        cls.cat_root = Category.create({"name": "Root", "color": 1})
        cls.cat_child1 = Category.create(
            {"name": "Child1", "color": 2, "parent": cls.cat_root.id}
        )
        cls.cat_child2 = Category.create(
            {"name": "Child2", "color": 3, "parent": cls.cat_root.id}
        )
        cls.categories = cls.cat_root | cls.cat_child1 | cls.cat_child2

        cls.discussion = cls.env["test_orm.discussion"].create(
            {
                "name": "Test Discussion",
                "categories": [(4, cls.cat_root.id), (4, cls.cat_child1.id)],
                "participants": [(4, cls.env.uid)],
            }
        )
        cls.msg1 = cls.env["test_orm.message"].create(
            {
                "discussion": cls.discussion.id,
                "body": "Hello",
                "important": True,
            }
        )
        cls.msg2 = cls.env["test_orm.message"].create(
            {
                "discussion": cls.discussion.id,
                "body": "World",
                "important": False,
            }
        )
        cls.messages = cls.msg1 | cls.msg2

    def test_mapped_field_name(self):
        names = self.categories.mapped("name")
        self.assertIsInstance(names, list)
        self.assertEqual(set(names), {"Root", "Child1", "Child2"})

    def test_mapped_field_preserves_order(self):
        names = self.categories.mapped("name")
        self.assertEqual(names, ["Root", "Child1", "Child2"])

    def test_mapped_relational(self):
        parents = self.categories.mapped("parent")
        self.assertEqual(parents, self.cat_root)

    def test_mapped_dotted_path(self):
        names = self.messages.mapped("discussion.name")
        self.assertIsInstance(names, list)
        self.assertEqual(names, ["Test Discussion"])

    def test_mapped_dotted_relational(self):
        categories = self.messages.mapped("discussion.categories")
        self.assertEqual(len(categories), 2)
        self.assertEqual(categories, self.cat_root | self.cat_child1)

    def test_mapped_callable(self):
        result = self.categories.mapped(lambda r: r.name.upper())
        self.assertEqual(result, ["ROOT", "CHILD1", "CHILD2"])

    def test_mapped_callable_returns_recordset(self):
        result = self.categories.mapped(lambda r: r.parent)
        self.assertEqual(result, self.cat_root)

    def test_mapped_empty_recordset(self):
        empty = self.env["test_orm.category"]
        result = empty.mapped("name")
        self.assertEqual(result, [])

    def test_mapped_empty_recordset_relational(self):
        empty = self.env["test_orm.category"]
        result = empty.mapped("parent")
        self.assertFalse(result)
        self.assertEqual(result._name, "test_orm.category")

    def test_mapped_falsy_func(self):
        self.assertEqual(self.categories.mapped(None), self.categories)
        self.assertEqual(self.categories.mapped(False), self.categories)

    def test_mapped_empty_string(self):
        self.assertEqual(self.categories.mapped(""), self.categories)

    def test_mapped_integer_field(self):
        colors = self.categories.mapped("color")
        self.assertEqual(colors, [1, 2, 3])
        self.assertTrue(all(isinstance(c, int) for c in colors))

    def test_mapped_boolean_field(self):
        important = self.messages.mapped("important")
        self.assertEqual(important, [True, False])


class TestFiltered(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Category = cls.env["test_orm.category"]
        cls.cat_a = Category.create({"name": "Filt A", "color": 1})
        cls.cat_b = Category.create({"name": "Filt B", "color": 0})
        cls.cat_c = Category.create(
            {"name": "Filt C", "color": 3, "parent": cls.cat_a.id}
        )
        cls.all_cats = cls.cat_a | cls.cat_b | cls.cat_c

    def test_filtered_callable(self):
        result = self.all_cats.filtered(lambda r: r.color > 0)
        self.assertEqual(result, self.cat_a | self.cat_c)

    def test_filtered_field_name(self):
        result = self.all_cats.filtered("color")
        self.assertEqual(result, self.cat_a | self.cat_c)

    def test_filtered_dotted_field(self):
        result = self.all_cats.filtered("parent.color")
        self.assertEqual(result, self.cat_c)

    def test_filtered_domain(self):
        result = self.all_cats.filtered(Domain([("color", ">", 0)]))
        self.assertEqual(result, self.cat_a | self.cat_c)

    def test_filtered_empty_func(self):
        result = self.all_cats.filtered(None)
        self.assertEqual(result, self.all_cats)

    def test_filtered_false_func(self):
        result = self.all_cats.filtered(False)
        self.assertEqual(result, self.all_cats)

    def test_filtered_empty_recordset(self):
        empty = self.env["test_orm.category"]
        result = empty.filtered(lambda r: r.color > 0)
        self.assertFalse(result)

    def test_filtered_none_pass(self):
        result = self.all_cats.filtered(lambda r: r.color > 100)
        self.assertFalse(result)
        self.assertEqual(result._name, "test_orm.category")

    def test_filtered_preserves_order(self):
        result = self.all_cats.filtered(lambda r: r.name in ("Filt C", "Filt A"))
        self.assertEqual(list(result._ids), [self.cat_a.id, self.cat_c.id])

    def test_filtered_all_pass(self):
        result = self.all_cats.filtered(lambda r: True)
        self.assertEqual(result, self.all_cats)

    def test_filtered_invalid_type(self):
        with self.assertRaises(TypeError):
            self.all_cats.filtered(42)

    def test_filtered_empty_domain(self):
        result = self.all_cats.filtered(Domain([]))
        self.assertEqual(result, self.all_cats)


class TestGrouped(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Category = cls.env["test_orm.category"]
        cls.cat_root = Category.create({"name": "Grp Root", "color": 1})
        cls.cat_a = Category.create(
            {"name": "Grp A", "color": 1, "parent": cls.cat_root.id}
        )
        cls.cat_b = Category.create(
            {"name": "Grp B", "color": 2, "parent": cls.cat_root.id}
        )
        cls.cat_c = Category.create({"name": "Grp C", "color": 2})
        cls.all_cats = cls.cat_root | cls.cat_a | cls.cat_b | cls.cat_c

    def test_grouped_string_key(self):
        groups = self.all_cats.grouped("color")
        self.assertIn(1, groups)
        self.assertIn(2, groups)
        self.assertEqual(len(groups[1]), 2)
        self.assertEqual(len(groups[2]), 2)

    def test_grouped_callable_key(self):
        groups = self.all_cats.grouped(lambda r: bool(r.parent))
        self.assertIn(True, groups)
        self.assertIn(False, groups)
        self.assertEqual(len(groups[True]), 2)
        self.assertEqual(len(groups[False]), 2)

    def test_grouped_preserves_prefetch(self):
        groups = self.all_cats.grouped("color")
        for group in groups.values():
            self.assertEqual(group._prefetch_ids, self.all_cats._prefetch_ids)

    def test_grouped_empty(self):
        empty = self.env["test_orm.category"]
        result = empty.grouped("color")
        self.assertEqual(result, {})

    def test_grouped_single_group(self):
        same_color = self.cat_root | self.cat_a
        groups = same_color.grouped("color")
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[1]), 2)

    def test_grouped_all_unique(self):
        records = self.cat_root | self.cat_a | self.cat_b | self.cat_c
        groups = records.grouped("name")
        self.assertEqual(len(groups), 4)
        for group in groups.values():
            self.assertEqual(len(group), 1)

    def test_grouped_falsy_key(self):
        groups = self.all_cats.grouped("parent")
        false_key = self.env["test_orm.category"]
        self.assertIn(false_key, groups)
        self.assertEqual(len(groups[false_key]), 2)

    def test_grouped_relational_key(self):
        groups = self.all_cats.grouped("parent")
        self.assertIn(self.cat_root, groups)
        self.assertEqual(groups[self.cat_root], self.cat_a | self.cat_b)


class TestFilteredDomain(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Category = cls.env["test_orm.category"]
        cls.cat_a = Category.create({"name": "Dom A", "color": 5})
        cls.cat_b = Category.create({"name": "Dom B", "color": 10})
        cls.cat_c = Category.create({"name": "Dom C", "color": 15})
        cls.all_cats = cls.cat_a | cls.cat_b | cls.cat_c

    def test_filtered_domain_basic(self):
        result = self.all_cats.filtered_domain([("color", ">=", 10)])
        self.assertEqual(result, self.cat_b | self.cat_c)

    def test_filtered_domain_empty(self):
        result = self.all_cats.filtered_domain([])
        self.assertEqual(result, self.all_cats)

    def test_filtered_domain_complex(self):
        result = self.all_cats.filtered_domain(
            [
                "|",
                ("color", "=", 5),
                ("color", "=", 15),
            ]
        )
        self.assertEqual(result, self.cat_a | self.cat_c)

    def test_filtered_domain_no_match(self):
        result = self.all_cats.filtered_domain([("color", ">", 100)])
        self.assertFalse(result)

    def test_filtered_domain_preserves_order(self):
        result = self.all_cats.filtered_domain([("color", "<=", 10)])
        self.assertEqual(list(result._ids), [self.cat_a.id, self.cat_b.id])

    def test_filtered_domain_on_empty(self):
        empty = self.env["test_orm.category"]
        result = empty.filtered_domain([("color", "=", 5)])
        self.assertFalse(result)


class TestCycleDetection(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Category = cls.env["test_orm.category"]
        cls.cat_a = Category.create({"name": "Cycle A"})
        cls.cat_b = Category.create({"name": "Cycle B", "parent": cls.cat_a.id})
        cls.cat_c = Category.create({"name": "Cycle C", "parent": cls.cat_b.id})

    def test_no_cycle(self):
        self.assertFalse(self.cat_a._has_cycle())
        self.assertFalse(self.cat_b._has_cycle())
        self.assertFalse(self.cat_c._has_cycle())

    def test_self_cycle(self):
        self.env.cr.execute(
            "UPDATE test_orm_category SET parent = %s WHERE id = %s",
            (self.cat_a.id, self.cat_a.id),
        )
        self.cat_a.invalidate_recordset()
        self.assertTrue(self.cat_a._has_cycle())

    def test_indirect_cycle(self):
        self.env.cr.execute(
            "UPDATE test_orm_category SET parent = %s WHERE id = %s",
            (self.cat_c.id, self.cat_a.id),
        )
        self.cat_a.invalidate_recordset()
        self.cat_b.invalidate_recordset()
        self.cat_c.invalidate_recordset()
        self.assertTrue(self.cat_a._has_cycle())
        self.assertTrue(self.cat_b._has_cycle())
        self.assertTrue(self.cat_c._has_cycle())

    def test_empty_recordset(self):
        empty = self.env["test_orm.category"]
        self.assertFalse(empty._has_cycle())

    def test_invalid_field(self):
        with self.assertRaises(ValueError):
            self.cat_a._has_cycle("nonexistent_field")

    def test_invalid_field_type(self):
        with self.assertRaises(ValueError):
            self.cat_a._has_cycle("name")

    def test_non_self_relational(self):
        with self.assertRaises(ValueError):
            self.env["test_orm.discussion"].create({"name": "X"})._has_cycle(
                "moderator"
            )


class TestCycleCheckOnCreate(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"]
        cls.root = Partner.create({"name": "Cycle Root", "is_company": True})
        cls.child = Partner.create({"name": "Cycle Child", "parent_id": cls.root.id})

    def _create_under_child(self) -> int:
        self.env.flush_all()
        before = self.cr.sql_statement_count
        self.env["res.partner"].create(
            {"name": "Cycle Grandchild", "parent_id": self.child.id}
        )
        self.env.flush_all()
        return self.cr.sql_statement_count - before

    def test_a_create_under_a_valid_parent_runs_no_cycle_query(self):
        self._create_under_child()
        checked = self._create_under_child()
        transaction = type(self.env.transaction)
        with patch.object(transaction, "is_checking_inserted", return_value=False):
            unchecked = self._create_under_child()
        self.assertEqual(self._create_under_child(), checked)
        self.assertEqual(unchecked, checked + 1)

    def test_a_write_that_closes_a_cycle_is_refused(self):
        grandchild = self.env["res.partner"].create(
            {"name": "Cycle Grandchild", "parent_id": self.child.id}
        )
        with self.assertRaisesRegex(ValidationError, "recursive"):
            self.root.parent_id = grandchild

    def test_a_create_that_links_its_own_ancestor_as_a_child_is_refused(self):
        with self.assertRaisesRegex(ValidationError, "recursive"):
            self.env["res.partner"].create(
                {
                    "name": "Cycle Loop",
                    "parent_id": self.child.id,
                    "child_ids": [Command.link(self.root.id)],
                }
            )

    def test_a_create_then_a_write_in_one_transaction_that_closes_a_cycle_is_refused(
        self,
    ):
        Partner = self.env["res.partner"]
        top = Partner.create({"name": "Cycle Top", "is_company": True})
        middle = Partner.create({"name": "Cycle Middle", "parent_id": top.id})
        bottom = Partner.create({"name": "Cycle Bottom", "parent_id": middle.id})
        with self.assertRaisesRegex(ValidationError, "recursive"):
            top.parent_id = bottom

    def test_a_batch_create_whose_parent_is_created_in_the_same_call(self):
        Partner = self.env["res.partner"]
        first, second = Partner.create(
            [
                {
                    "name": "Batch Parent",
                    "is_company": True,
                    "child_ids": [
                        Command.create(
                            {
                                "name": "Batch Child",
                                "child_ids": [Command.create({"name": "Batch Leaf"})],
                            }
                        )
                    ],
                },
                {"name": "Batch Sibling", "parent_id": self.child.id},
            ]
        )
        leaf = first.child_ids.child_ids
        self.assertEqual(leaf.name, "Batch Leaf")
        self.assertEqual(leaf.parent_id.parent_id, first)
        self.assertEqual(second.parent_id, self.child)
        self.assertFalse((first | first.child_ids | leaf | second)._has_cycle())
        with self.assertRaisesRegex(ValidationError, "recursive"):
            first.parent_id = leaf


class TestCycleCheckOnParentStoreCreate(TransactionCase):
    def test_a_parent_store_tree_created_in_one_call_keeps_its_paths(self):
        Menu = self.env["ir.ui.menu"]
        root = Menu.create(
            {
                "name": "Cycle Menu Root",
                "child_id": [
                    Command.create(
                        {
                            "name": "Cycle Menu Child",
                            "child_id": [Command.create({"name": "Cycle Menu Leaf"})],
                        }
                    )
                ],
            }
        )
        child = root.child_id
        leaf = child.child_id
        self.env.flush_all()
        self.assertEqual(child.parent_path, f"{root.id}/{child.id}/")
        self.assertEqual(leaf.parent_path, f"{root.id}/{child.id}/{leaf.id}/")
        self.assertFalse((root | child | leaf)._has_cycle())
        # the parent_path update refuses it, in the model's own words
        with self.assertRaisesRegex(UserError, "recursive menus"):
            root.parent_id = leaf

    def test_a_parent_store_create_runs_no_cycle_query(self):
        Menu = self.env["ir.ui.menu"]
        parent = Menu.create({"name": "Cycle Menu Parent"})

        def create_child() -> int:
            self.env.flush_all()
            before = self.cr.sql_statement_count
            Menu.create({"name": "Cycle Menu Child", "parent_id": parent.id})
            self.env.flush_all()
            return self.cr.sql_statement_count - before

        create_child()
        checked = create_child()
        transaction = type(self.env.transaction)
        with patch.object(transaction, "is_checking_inserted", return_value=False):
            unchecked = create_child()
        # a new row has no descendants: no cycle query, whether or not the
        # transaction would check the rows it inserted
        self.assertEqual(unchecked, checked)
