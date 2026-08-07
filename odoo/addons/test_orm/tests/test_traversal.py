from odoo.fields import Domain
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
