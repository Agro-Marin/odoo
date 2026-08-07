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
        self.assertEqual(self.cache.locked_tables, set())
        self.cache.locked_tables.add("t")
        self.assertIn("t", self.cache.locked_tables)

    def test_clear_drops_every_fact_including_the_lock_record(self):
        self.cache.set_id_sequence("t", "s")
        self.cache.set_column_types("t", ["a"], [23])
        self.cache.locked_tables.add("t")
        self.cache.clear()
        self.assertIsNone(self.cache.get_id_sequence("t"))
        self.assertIsNone(self.cache.get_column_types("t", ["a"]))
        self.assertEqual(self.cache.locked_tables, set())

    def test_instances_are_independent(self):
        other = TransactionSchemaCache()
        self.cache.set_column_types("t", ["a"], [23])
        self.assertIsNone(other.get_column_types("t", ["a"]))


class TestClearSeparatesTwoLifetimes(unittest.TestCase):
    def setUp(self):
        self.cache = TransactionSchemaCache()
        self.cache.set_id_sequence("t", "t_id_seq")
        self.cache.set_column_types("t", ["a"], [23])
        self.cache.locked_tables.add("t")

    def test_clear_catalog_facts_keeps_the_lock_ledger(self):
        self.cache.clear_catalog_facts()
        self.assertIsNone(self.cache.get_id_sequence("t"))
        self.assertIsNone(self.cache.get_column_types("t", ["a"]))
        self.assertIn("t", self.cache.locked_tables, "the lock is still held")

    def test_clear_drops_the_lock_ledger_too(self):
        self.cache.clear()
        self.assertIsNone(self.cache.get_id_sequence("t"))
        self.assertEqual(self.cache.locked_tables, set())

    def test_repr_reports_all_three_populations(self):
        self.assertEqual(
            repr(self.cache),
            "TransactionSchemaCache(sequences=1, column_types=1, locked=1)",
        )


if __name__ == "__main__":
    unittest.main()
