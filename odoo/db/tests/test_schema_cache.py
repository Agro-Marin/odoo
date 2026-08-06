"""Tier-1 (database-free) tests for :mod:`odoo.db.schema_cache`.

:class:`TransactionSchemaCache` is pure dict bookkeeping; what makes it
*correct* — that its entries are read under the ``ROW EXCLUSIVE`` lock
``copy_from`` takes, and never outlive the transaction holding that lock —
needs a live backend and is covered by ``TestBulkCatalogFactScope`` and
``TestConcurrentDdlDuringBinaryCopy`` in
``odoo/addons/base/tests/test_db_cursor.py``.

The rules the previous process-global cache needed (dbname keying,
never-cache-temp, race-free clear) are gone by construction: one instance per
cursor cannot be shared between databases, sessions, or a concurrent clear.
"""

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
    """Catalog facts and the lock ledger expire on different events.

    A ``ROW EXCLUSIVE`` lock is held to the end of the transaction, so DDL —
    which does not end one — invalidates what was read from the catalog but not
    the fact that the lock was taken.  Clearing both on DDL made the next
    ``copy_from`` re-issue a ``LOCK TABLE`` it already held.
    """

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
