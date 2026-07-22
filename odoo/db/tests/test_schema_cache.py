"""Tier-1 (database-free) tests for :mod:`odoo.db.schema_cache`.

:class:`SchemaCache` is pure dict bookkeeping with three correctness rules
(dbname keying, never-cache-temp, race-free clear — see its module docstring),
all expressible without a database.  The concurrency test is adapted from the
integration suite's ``TestSchemaCacheClearConcurrency``, which exercised the
same logic through the ``_clear_schema_caches`` cursor-layer delegate.
"""

import threading
import time
import unittest

from odoo.db.schema_cache import SchemaCache


class TestSchemaCacheBasics(unittest.TestCase):
    def setUp(self):
        self.cache = SchemaCache()

    def test_id_sequence_roundtrip_keyed_by_db(self):
        self.cache.set_id_sequence("db1", "t", "t_id_seq")
        self.assertEqual(self.cache.get_id_sequence("db1", "t"), "t_id_seq")
        # dbname keying: another database's same-named table is a miss
        self.assertIsNone(self.cache.get_id_sequence("db2", "t"))

    def test_temp_sequence_never_cached(self):
        # pg_temp names are session-local; the name-based key would resolve
        # them to the wrong (or a nonexistent) sequence in another session.
        self.cache.set_id_sequence("db1", "t", "pg_temp.t_id_seq")
        self.assertIsNone(self.cache.get_id_sequence("db1", "t"))
        self.cache.set_id_sequence("db1", "t", "pg_temp_3.t_id_seq")
        self.assertIsNone(self.cache.get_id_sequence("db1", "t"))

    def test_column_types_keyed_by_columns_tuple(self):
        self.cache.set_column_types(
            "db1", "t", ["a", "b"], ["int4", "text"], namespace="public"
        )
        self.assertEqual(
            self.cache.get_column_types("db1", "t", ["a", "b"]), ["int4", "text"]
        )
        # a different column selection is a distinct entry
        self.assertIsNone(self.cache.get_column_types("db1", "t", ["a"]))
        # list/tuple forms of the same columns hit the same entry
        self.assertEqual(
            self.cache.get_column_types("db1", "t", ("a", "b")), ["int4", "text"]
        )

    def test_temp_namespace_never_cached(self):
        self.cache.set_column_types("db1", "t", ["a"], ["int4"], namespace="pg_temp_7")
        self.assertIsNone(self.cache.get_column_types("db1", "t", ["a"]))

    def test_clear_per_database_and_all(self):
        self.cache.set_id_sequence("db1", "t", "s1")
        self.cache.set_id_sequence("db2", "t", "s2")
        self.cache.set_column_types("db1", "t", ["a"], ["int4"], namespace="public")
        self.cache.clear("db1")
        self.assertIsNone(self.cache.get_id_sequence("db1", "t"))
        self.assertIsNone(self.cache.get_column_types("db1", "t", ["a"]))
        self.assertEqual(self.cache.get_id_sequence("db2", "t"), "s2")
        self.cache.clear()
        self.assertIsNone(self.cache.get_id_sequence("db2", "t"))


class TestSchemaCacheClearConcurrency(unittest.TestCase):
    """``clear()`` iterates the cache while ``copy_from`` populates it from
    other threads.  Iterating a live dict while another thread inserts raises
    'dictionary changed size during iteration'; the fix snapshots the keys via
    ``list(cache)`` before filtering (see the module docstring).
    """

    def test_clear_does_not_race_concurrent_populate(self):
        cache = SchemaCache()
        backing = cache._id_sequences
        errors = []
        stop = threading.Event()

        def populate():
            i = 0
            while not stop.is_set():
                backing[("otherdb", f"t{i}")] = "seq"
                i += 1
                if i % 5000 == 0:
                    backing.clear()

        def clear_loop():
            while not stop.is_set():
                try:
                    cache.clear("targetdb")
                except RuntimeError as e:
                    errors.append(str(e))
                    return

        threads = [
            threading.Thread(target=populate),
            threading.Thread(target=clear_loop),
        ]
        for t in threads:
            t.start()
        time.sleep(1.0)
        stop.set()
        for t in threads:
            t.join()

        self.assertEqual(
            errors, [], "SchemaCache.clear raced the cache dict — fix regressed"
        )


if __name__ == "__main__":
    unittest.main()
