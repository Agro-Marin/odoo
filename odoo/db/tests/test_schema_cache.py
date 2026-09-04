import unittest

from odoo.db.schema_cache import TransactionSchemaCache


class TestTransactionSchemaCache(unittest.TestCase):
    def setUp(self):
        self.cache = TransactionSchemaCache()

    def test_id_sequence_roundtrip(self):
        self.assertIsNone(self.cache.get_id_sequence("t"))
        self.cache.set_id_sequence("t", "t_id_seq")
        self.assertEqual(self.cache.get_id_sequence("t"), "t_id_seq")

    def test_temp_sequence_is_cacheable(self):
        self.cache.set_id_sequence("t", "pg_temp_3.t_id_seq")
        self.assertEqual(self.cache.get_id_sequence("t"), "pg_temp_3.t_id_seq")

    def test_column_types_keyed_by_columns_tuple(self):
        self.cache.set_column_types("t", ["a", "b"], [23, 25])
        self.assertEqual(self.cache.get_column_types("t", ["a", "b"]), [23, 25])
        self.assertIsNone(self.cache.get_column_types("t", ["a"]))
        self.assertEqual(self.cache.get_column_types("t", ("a", "b")), [23, 25])

    def test_locked_tables_tracks_the_lock_taken_once_per_table(self):
        self.assertFalse(self.cache.is_locked("t"))
        self.cache.mark_locked("t", 0)
        self.assertTrue(self.cache.is_locked("t"))

    def test_mark_locked_keeps_the_first_recorded_depth(self):
        self.cache.mark_locked("t", 0)
        self.cache.mark_locked("t", 2)
        self.cache.release_locks_since_depth(2)
        self.assertTrue(self.cache.is_locked("t"), "recorded at depth 0, not 2")

    def test_clear_drops_every_fact_including_the_lock_record(self):
        self.cache.set_id_sequence("t", "s")
        self.cache.set_column_types("t", ["a"], [23])
        self.cache.mark_locked("t", 0)
        self.cache.clear()
        self.assertIsNone(self.cache.get_id_sequence("t"))
        self.assertIsNone(self.cache.get_column_types("t", ["a"]))
        self.assertFalse(self.cache.is_locked("t"))

    def test_instances_are_independent(self):
        other = TransactionSchemaCache()
        self.cache.set_column_types("t", ["a"], [23])
        self.assertIsNone(other.get_column_types("t", ["a"]))


class TestClearSeparatesTwoLifetimes(unittest.TestCase):
    def setUp(self):
        self.cache = TransactionSchemaCache()
        self.cache.set_id_sequence("t", "t_id_seq")
        self.cache.set_column_types("t", ["a"], [23])
        self.cache.mark_locked("t", 0)

    def test_invalidate_catalog_facts_keeps_the_lock_ledger(self):
        self.cache.invalidate_catalog_facts()
        self.assertIsNone(self.cache.get_id_sequence("t"))
        self.assertIsNone(self.cache.get_column_types("t", ["a"]))
        self.assertTrue(self.cache.is_locked("t"), "the lock is still held")

    def test_clear_drops_the_lock_ledger_too(self):
        self.cache.clear()
        self.assertIsNone(self.cache.get_id_sequence("t"))
        self.assertFalse(self.cache.is_locked("t"))

    def test_repr_reports_all_three_populations(self):
        self.assertEqual(
            repr(self.cache),
            "TransactionSchemaCache(sequences=1, column_types=1, locked=1)",
        )


class TestReleaseLocksSinceDepth(unittest.TestCase):
    def setUp(self):
        self.cache = TransactionSchemaCache()

    def test_releases_only_tables_locked_at_or_after_the_given_depth(self):
        self.cache.set_id_sequence("outer", "outer_seq")
        self.cache.set_column_types("outer", ["a"], [23])
        self.cache.mark_locked("outer", 0)

        self.cache.set_id_sequence("inner", "inner_seq")
        self.cache.set_column_types("inner", ["a"], [23])
        self.cache.mark_locked("inner", 1)

        self.cache.release_locks_since_depth(1)

        self.assertTrue(self.cache.is_locked("outer"), "locked before the savepoint")
        self.assertEqual(self.cache.get_id_sequence("outer"), "outer_seq")
        self.assertEqual(self.cache.get_column_types("outer", ["a"]), [23])

        self.assertFalse(self.cache.is_locked("inner"), "locked inside the savepoint")
        self.assertIsNone(self.cache.get_id_sequence("inner"))
        self.assertIsNone(self.cache.get_column_types("inner", ["a"]))

    def test_no_locks_at_depth_is_a_no_op(self):
        self.cache.mark_locked("outer", 0)
        self.cache.release_locks_since_depth(1)
        self.assertTrue(self.cache.is_locked("outer"))


if __name__ == "__main__":
    unittest.main()
