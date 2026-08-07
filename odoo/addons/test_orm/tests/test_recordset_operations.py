import copy

from odoo.tests.common import TransactionCase


class TestRecordsetSetOperations(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Category = cls.env["test_orm.category"]
        cls.cat_a = Category.create({"name": "Alpha"})
        cls.cat_b = Category.create({"name": "Beta"})
        cls.cat_c = Category.create({"name": "Gamma"})
        cls.cat_d = Category.create({"name": "Delta"})
        cls.all_cats = cls.cat_a | cls.cat_b | cls.cat_c | cls.cat_d

    def test_union_basic(self):
        r1 = self.cat_a | self.cat_b
        r2 = self.cat_c | self.cat_d
        result = r1 | r2
        self.assertEqual(len(result), 4)
        self.assertEqual(set(result.ids), set(self.all_cats.ids))

    def test_union_preserves_order(self):
        r1 = self.cat_b | self.cat_a
        r2 = self.cat_d | self.cat_c
        result = r1 | r2
        self.assertEqual(
            list(result._ids),
            [self.cat_b.id, self.cat_a.id, self.cat_d.id, self.cat_c.id],
        )

    def test_union_removes_duplicates(self):
        r1 = self.cat_a | self.cat_b | self.cat_c
        r2 = self.cat_b | self.cat_c | self.cat_d
        result = r1 | r2
        self.assertEqual(len(result), 4)

    def test_union_empty(self):
        empty = self.env["test_orm.category"]
        result = self.cat_a | empty
        self.assertEqual(result, self.cat_a)
        result = empty | self.cat_a
        self.assertEqual(result, self.cat_a)

    def test_union_self(self):
        r = self.cat_a | self.cat_b
        result = r | r
        self.assertEqual(len(result), 2)
        self.assertEqual(result, r)

    def test_union_multiple(self):
        result = self.cat_a.union(self.cat_b, self.cat_c, self.cat_d)
        self.assertEqual(len(result), 4)
        self.assertEqual(result, self.all_cats)

    def test_intersection_basic(self):
        r1 = self.cat_a | self.cat_b | self.cat_c
        r2 = self.cat_b | self.cat_c | self.cat_d
        result = r1 & r2
        self.assertEqual(len(result), 2)
        self.assertEqual(result, self.cat_b | self.cat_c)

    def test_intersection_preserves_order(self):
        r1 = self.cat_c | self.cat_b | self.cat_a
        r2 = self.cat_a | self.cat_c
        result = r1 & r2
        self.assertEqual(list(result._ids), [self.cat_c.id, self.cat_a.id])

    def test_intersection_empty(self):
        empty = self.env["test_orm.category"]
        result = self.all_cats & empty
        self.assertFalse(result)

    def test_intersection_disjoint(self):
        r1 = self.cat_a | self.cat_b
        r2 = self.cat_c | self.cat_d
        result = r1 & r2
        self.assertFalse(result)
        self.assertEqual(len(result), 0)

    def test_difference_basic(self):
        r1 = self.cat_a | self.cat_b | self.cat_c
        r2 = self.cat_b | self.cat_d
        result = r1 - r2
        self.assertEqual(len(result), 2)
        self.assertEqual(result, self.cat_a | self.cat_c)

    def test_difference_preserves_order(self):
        r1 = self.cat_c | self.cat_b | self.cat_a
        r2 = self.cat_b
        result = r1 - r2
        self.assertEqual(list(result._ids), [self.cat_c.id, self.cat_a.id])

    def test_difference_empty(self):
        empty = self.env["test_orm.category"]
        result = self.all_cats - empty
        self.assertEqual(result, self.all_cats)

    def test_difference_self(self):
        result = self.all_cats - self.all_cats
        self.assertFalse(result)
        self.assertEqual(len(result), 0)

    def test_concat_basic(self):
        r1 = self.cat_a | self.cat_b
        r2 = self.cat_c | self.cat_d
        result = r1 + r2
        self.assertEqual(len(result), 4)

    def test_concat_preserves_duplicates(self):
        r1 = self.cat_a | self.cat_b
        r2 = self.cat_b | self.cat_c
        result = r1 + r2
        self.assertEqual(len(result), 4)
        self.assertEqual(
            list(result._ids),
            [self.cat_a.id, self.cat_b.id, self.cat_b.id, self.cat_c.id],
        )

    def test_concat_multiple(self):
        result = self.cat_a.concat(self.cat_b, self.cat_c)
        self.assertEqual(len(result), 3)

    def test_type_error_different_models(self):
        partner = self.env["res.partner"].search([], limit=1)
        with self.assertRaises(TypeError):
            self.cat_a | partner
        with self.assertRaises(TypeError):
            self.cat_a & partner
        with self.assertRaises(TypeError):
            self.cat_a - partner
        with self.assertRaises(TypeError):
            self.cat_a + partner

    def test_type_error_non_recordset(self):
        with self.assertRaises(TypeError):
            self.cat_a | "string"
        with self.assertRaises(TypeError):
            self.cat_a & 42
        with self.assertRaises(TypeError):
            self.cat_a - [1, 2, 3]
        with self.assertRaises(TypeError):
            self.cat_a + None


class TestRecordsetComparison(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Category = cls.env["test_orm.category"]
        cls.cat_a = Category.create({"name": "Cmp A"})
        cls.cat_b = Category.create({"name": "Cmp B"})
        cls.cat_c = Category.create({"name": "Cmp C"})

    def test_eq_same_records(self):
        r1 = self.cat_a | self.cat_b
        r2 = self.cat_a | self.cat_b
        self.assertEqual(r1, r2)

    def test_eq_different_order(self):
        r1 = self.cat_a | self.cat_b
        r2 = self.cat_b | self.cat_a
        self.assertEqual(r1, r2)

    def test_eq_different_records(self):
        r1 = self.cat_a | self.cat_b
        r2 = self.cat_a | self.cat_c
        self.assertNotEqual(r1, r2)

    def test_eq_empty(self):
        empty1 = self.env["test_orm.category"]
        empty2 = self.env["test_orm.category"]
        self.assertEqual(empty1, empty2)

    def test_lt_proper_subset(self):
        r1 = self.cat_a | self.cat_b
        r2 = self.cat_a | self.cat_b | self.cat_c
        self.assertTrue(r1 < r2)
        self.assertFalse(r2 < r1)

    def test_lt_equal_sets(self):
        r1 = self.cat_a | self.cat_b
        r2 = self.cat_a | self.cat_b
        self.assertFalse(r1 < r2)

    def test_le_subset_or_equal(self):
        r1 = self.cat_a | self.cat_b
        r2 = self.cat_a | self.cat_b | self.cat_c
        self.assertTrue(r1 <= r2)
        self.assertFalse(r2 <= r1)

    def test_le_self(self):
        r = self.cat_a | self.cat_b
        self.assertTrue(r <= r)

    def test_le_empty(self):
        empty = self.env["test_orm.category"]
        self.assertTrue(empty <= self.cat_a)

    def test_gt_proper_superset(self):
        r1 = self.cat_a | self.cat_b | self.cat_c
        r2 = self.cat_a | self.cat_b
        self.assertTrue(r1 > r2)
        self.assertFalse(r2 > r1)

    def test_ge_superset_or_equal(self):
        r1 = self.cat_a | self.cat_b | self.cat_c
        r2 = self.cat_a | self.cat_b
        self.assertTrue(r1 >= r2)
        self.assertTrue(r1 >= r1)

    def test_ne_different(self):
        r1 = self.cat_a | self.cat_b
        r2 = self.cat_b | self.cat_c
        self.assertTrue(r1 != r2)
        self.assertFalse(r1 != r1)

    def test_comparison_different_model(self):
        partner = self.env["res.partner"].search([], limit=1)
        result = self.cat_a.__lt__(partner)
        self.assertIs(result, NotImplemented)

    def test_singleton_in_recordset(self):
        r = self.cat_a | self.cat_b | self.cat_c
        self.assertTrue(self.cat_a <= r)
        self.assertTrue(self.cat_a in r)


class TestRecordsetIteration(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Category = cls.env["test_orm.category"]
        cls.cat_a = Category.create({"name": "Iter Alpha"})
        cls.cat_b = Category.create({"name": "Iter Beta"})
        cls.cat_c = Category.create({"name": "Iter Gamma"})
        cls.records = cls.cat_a | cls.cat_b | cls.cat_c

    def test_iter_basic(self):
        result = list(self.records)
        self.assertEqual(len(result), 3)
        for r in result:
            self.assertEqual(len(r), 1)
        self.assertEqual(result[0], self.cat_a)
        self.assertEqual(result[1], self.cat_b)
        self.assertEqual(result[2], self.cat_c)

    def test_iter_empty(self):
        empty = self.env["test_orm.category"]
        result = list(empty)
        self.assertEqual(result, [])

    def test_iter_single(self):
        result = list(self.cat_a)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], self.cat_a)

    def test_reversed_basic(self):
        result = list(reversed(self.records))
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], self.cat_c)
        self.assertEqual(result[1], self.cat_b)
        self.assertEqual(result[2], self.cat_a)

    def test_reversed_empty(self):
        empty = self.env["test_orm.category"]
        result = list(reversed(empty))
        self.assertEqual(result, [])

    def test_reversed_single(self):
        result = list(reversed(self.cat_a))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], self.cat_a)

    def test_contains_record(self):
        self.assertIn(self.cat_a, self.records)
        self.assertIn(self.cat_b, self.records)
        self.assertIn(self.cat_c, self.records)

    def test_contains_record_not_found(self):
        other = self.env["test_orm.category"].create({"name": "Other"})
        self.assertNotIn(other, self.records)

    def test_contains_field_name(self):
        self.assertIn("name", self.records)
        self.assertIn("color", self.records)

    def test_contains_invalid_field(self):
        self.assertNotIn("nonexistent_field_xyz", self.records)

    def test_contains_wrong_model(self):
        partner = self.env["res.partner"].search([], limit=1)
        with self.assertRaises(TypeError):
            partner in self.records

    def test_getitem_index(self):
        first = self.records[0]
        self.assertEqual(len(first), 1)
        self.assertEqual(first, self.cat_a)
        last = self.records[-1]
        self.assertEqual(last, self.cat_c)

    def test_getitem_slice(self):
        result = self.records[1:3]
        self.assertEqual(len(result), 2)
        self.assertEqual(result, self.cat_b | self.cat_c)

    def test_getitem_field(self):
        name = self.cat_a["name"]
        self.assertEqual(name, "Iter Alpha")

    def test_setitem_field(self):
        self.cat_a["name"] = "Modified Alpha"
        self.assertEqual(self.cat_a.name, "Modified Alpha")

    def test_len(self):
        self.assertEqual(len(self.records), 3)
        self.assertEqual(len(self.cat_a), 1)
        self.assertEqual(len(self.env["test_orm.category"]), 0)

    def test_index_returns_position(self):
        self.assertEqual(self.records.index(self.cat_a), 0)
        self.assertEqual(self.records.index(self.cat_b), 1)
        self.assertEqual(self.records.index(self.cat_c), 2)

    def test_index_raises_on_missing(self):
        other = self.env["test_orm.category"].create({"name": "other"})
        with self.assertRaises(ValueError):
            self.records.index(other)

    def test_index_negative_start_normalized(self):
        self.assertEqual(self.records.index(self.cat_c, -1), 2)
        self.assertEqual(self.records.index(self.cat_a, -3), 0)
        with self.assertRaises(ValueError):
            self.records.index(self.cat_a, -1)

    def test_index_negative_stop_normalized(self):
        with self.assertRaises(ValueError):
            self.records.index(self.cat_c, 0, -1)
        self.assertEqual(self.records.index(self.cat_a, 0, -1), 0)

    def test_bool_empty(self):
        empty = self.env["test_orm.category"]
        self.assertFalse(empty)
        self.assertFalse(bool(empty))

    def test_bool_nonempty(self):
        self.assertTrue(self.records)
        self.assertTrue(self.cat_a)

    def test_int_singleton(self):
        self.assertEqual(int(self.cat_a), self.cat_a.id)

    def test_int_empty(self):
        empty = self.env["test_orm.category"]
        self.assertEqual(int(empty), 0)

    def test_repr(self):
        r = repr(self.cat_a)
        self.assertIn("test_orm.category", r)
        self.assertIn(str(self.cat_a.id), r)

    def test_hash(self):
        r1 = self.cat_a | self.cat_b
        self.cat_a | self.cat_b
        s = {r1}
        self.assertIn(r1, s)

    def test_deepcopy_returns_self(self):
        result = copy.deepcopy(self.records)
        self.assertIs(result, self.records)

    def test_browse_single_int(self):
        record = self.env["test_orm.category"].browse(self.cat_a.id)
        self.assertEqual(len(record), 1)
        self.assertEqual(record.id, self.cat_a.id)

    def test_browse_list(self):
        ids = [self.cat_a.id, self.cat_b.id]
        records = self.env["test_orm.category"].browse(ids)
        self.assertEqual(len(records), 2)

    def test_browse_empty(self):
        empty = self.env["test_orm.category"].browse()
        self.assertFalse(empty)
        self.assertEqual(len(empty), 0)

    def test_ids_property(self):
        result = self.records.ids
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 3)
        self.assertTrue(all(isinstance(i, int) for i in result))
