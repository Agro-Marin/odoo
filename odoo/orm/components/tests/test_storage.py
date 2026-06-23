"""Pure-Python tests for DictBackend — no Odoo, no database required."""

import unittest

from odoo.orm.components.storage import DictBackend


class TestDictBackendInsert(unittest.TestCase):
    """Test insert operations."""

    def setUp(self) -> None:
        self.backend = DictBackend()

    def test_insert_single(self) -> None:
        ids = self.backend.insert_rows("partner", ["name"], [("Alice",)])
        self.assertEqual(len(ids), 1)
        self.assertEqual(ids[0], 1)

    def test_insert_multiple(self) -> None:
        ids = self.backend.insert_rows(
            "partner",
            ["name", "email"],
            [("Alice", "a@x.com"), ("Bob", "b@x.com")],
        )
        self.assertEqual(ids, [1, 2])

    def test_insert_auto_increment(self) -> None:
        ids1 = self.backend.insert_rows("partner", ["name"], [("Alice",)])
        ids2 = self.backend.insert_rows("partner", ["name"], [("Bob",)])
        self.assertEqual(ids1, [1])
        self.assertEqual(ids2, [2])

    def test_insert_different_tables(self) -> None:
        ids1 = self.backend.insert_rows("partner", ["name"], [("Alice",)])
        ids2 = self.backend.insert_rows("product", ["name"], [("Widget",)])
        # separate sequences
        self.assertEqual(ids1, [1])
        self.assertEqual(ids2, [1])

    def test_insert_empty(self) -> None:
        ids = self.backend.insert_rows("partner", ["name"], [])
        self.assertEqual(ids, [])


class TestDictBackendFetch(unittest.TestCase):
    """Test fetch operations."""

    def setUp(self) -> None:
        self.backend = DictBackend()
        self.backend.insert_rows(
            "partner",
            ["name", "email"],
            [("Alice", "a@x.com"), ("Bob", "b@x.com")],
        )

    def test_fetch_all_columns(self) -> None:
        rows = self.backend.fetch_rows("partner", [1, 2], ["name", "email"])
        self.assertEqual(rows, [("Alice", "a@x.com"), ("Bob", "b@x.com")])

    def test_fetch_subset_columns(self) -> None:
        rows = self.backend.fetch_rows("partner", [1], ["name"])
        self.assertEqual(rows, [("Alice",)])

    def test_fetch_missing_id(self) -> None:
        rows = self.backend.fetch_rows("partner", [999], ["name"])
        self.assertEqual(rows, [])

    def test_fetch_mixed_ids(self) -> None:
        rows = self.backend.fetch_rows("partner", [1, 999], ["name"])
        self.assertEqual(rows, [("Alice",)])

    def test_fetch_missing_column(self) -> None:
        rows = self.backend.fetch_rows("partner", [1], ["nonexistent"])
        self.assertEqual(rows, [(None,)])

    def test_fetch_empty_table(self) -> None:
        rows = self.backend.fetch_rows("empty_table", [1], ["name"])
        self.assertEqual(rows, [])


class TestDictBackendUpdate(unittest.TestCase):
    """Test update operations."""

    def setUp(self) -> None:
        self.backend = DictBackend()
        self.backend.insert_rows("partner", ["name", "email"], [("Alice", "a@x.com")])

    def test_update_single_field(self) -> None:
        self.backend.update_rows("partner", [(1, {"name": "Alicia"})])
        rows = self.backend.fetch_rows("partner", [1], ["name", "email"])
        self.assertEqual(rows, [("Alicia", "a@x.com")])

    def test_update_multiple_fields(self) -> None:
        self.backend.update_rows(
            "partner", [(1, {"name": "Alicia", "email": "new@x.com"})]
        )
        rows = self.backend.fetch_rows("partner", [1], ["name", "email"])
        self.assertEqual(rows, [("Alicia", "new@x.com")])

    def test_update_nonexistent_id(self) -> None:
        # should not raise
        self.backend.update_rows("partner", [(999, {"name": "Ghost"})])

    def test_update_nonexistent_table(self) -> None:
        # should not raise
        self.backend.update_rows("nonexistent", [(1, {"name": "Ghost"})])


class TestDictBackendDelete(unittest.TestCase):
    """Test delete operations."""

    def setUp(self) -> None:
        self.backend = DictBackend()
        self.backend.insert_rows(
            "partner",
            ["name"],
            [("Alice",), ("Bob",)],
        )

    def test_delete_single(self) -> None:
        self.backend.delete_rows("partner", [1])
        self.assertEqual(self.backend.row_count("partner"), 1)
        rows = self.backend.fetch_rows("partner", [1], ["name"])
        self.assertEqual(rows, [])

    def test_delete_multiple(self) -> None:
        self.backend.delete_rows("partner", [1, 2])
        self.assertEqual(self.backend.row_count("partner"), 0)

    def test_delete_nonexistent(self) -> None:
        # should not raise
        self.backend.delete_rows("partner", [999])
        self.assertEqual(self.backend.row_count("partner"), 2)

    def test_delete_nonexistent_table(self) -> None:
        # should not raise
        self.backend.delete_rows("nonexistent", [1])


class TestDictBackendHelpers(unittest.TestCase):
    """Test helper methods."""

    def setUp(self) -> None:
        self.backend = DictBackend()

    def test_get_row(self) -> None:
        self.backend.insert_rows("partner", ["name"], [("Alice",)])
        row = self.backend.get_row("partner", 1)
        self.assertEqual(row, {"name": "Alice"})

    def test_get_row_missing(self) -> None:
        self.assertIsNone(self.backend.get_row("partner", 1))

    def test_table_ids(self) -> None:
        self.backend.insert_rows("partner", ["name"], [("Alice",), ("Bob",)])
        self.assertEqual(self.backend.table_ids("partner"), [1, 2])

    def test_table_ids_empty(self) -> None:
        self.assertEqual(self.backend.table_ids("partner"), [])

    def test_row_count(self) -> None:
        self.assertEqual(self.backend.row_count("partner"), 0)
        self.backend.insert_rows("partner", ["name"], [("Alice",)])
        self.assertEqual(self.backend.row_count("partner"), 1)

    def test_repr(self) -> None:
        self.backend.insert_rows("partner", ["name"], [("Alice",)])
        r = repr(self.backend)
        self.assertIn("tables=1", r)
        self.assertIn("rows=1", r)


class TestDictBackendSealedApi(unittest.TestCase):
    """Public row API added so the ORM never touches ``_tables`` directly."""

    def setUp(self) -> None:
        self.backend = DictBackend()

    def test_put_rows_stores_by_id(self) -> None:
        self.backend.put_rows(
            "partner", [{"id": 5, "name": "Alice"}, {"id": 6, "name": "Bob"}]
        )
        self.assertEqual(self.backend.get_row("partner", 5), {"id": 5, "name": "Alice"})
        self.assertEqual(self.backend.table_ids("partner"), [5, 6])

    def test_put_rows_advances_sequence_past_explicit_id(self) -> None:
        # put_rows with id=5 must push next_id() beyond 5 to avoid collision
        self.backend.put_rows("partner", [{"id": 5, "name": "Alice"}])
        self.assertEqual(self.backend.next_id("partner"), 6)

    def test_put_rows_overwrites_same_id(self) -> None:
        self.backend.put_rows("partner", [{"id": 1, "name": "Alice"}])
        self.backend.put_rows("partner", [{"id": 1, "name": "Alice2"}])
        self.assertEqual(self.backend.row_count("partner"), 1)
        self.assertEqual(self.backend.get_row("partner", 1)["name"], "Alice2")

    def test_upsert_updates_existing(self) -> None:
        self.backend.put_rows("partner", [{"id": 1, "name": "Alice", "age": 30}])
        self.backend.upsert_rows("partner", [(1, {"age": 31})])
        self.assertEqual(self.backend.get_row("partner", 1), {"id": 1, "name": "Alice", "age": 31})

    def test_upsert_inserts_missing(self) -> None:
        # unlike update_rows, upsert creates a row for an unknown id
        self.backend.upsert_rows("partner", [(7, {"name": "New"})])
        self.assertEqual(self.backend.get_row("partner", 7), {"id": 7, "name": "New"})

    def test_update_rows_skips_missing(self) -> None:
        # contrast: update_rows must NOT create the row
        self.backend.update_rows("partner", [(7, {"name": "New"})])
        self.assertIsNone(self.backend.get_row("partner", 7))

    def test_get_rows_returns_only_existing(self) -> None:
        self.backend.put_rows("partner", [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}])
        rows = self.backend.get_rows("partner", [1, 2, 99])
        self.assertEqual(set(rows), {1, 2})
        self.assertEqual(rows[1]["name"], "A")

    def test_get_rows_unknown_table(self) -> None:
        self.assertEqual(self.backend.get_rows("nope", [1, 2]), {})

    def test_contains_ids(self) -> None:
        self.backend.put_rows("partner", [{"id": 1}, {"id": 3}])
        self.assertEqual(self.backend.contains_ids("partner", [1, 2, 3, 4]), {1, 3})

    def test_contains_ids_unknown_table(self) -> None:
        self.assertEqual(self.backend.contains_ids("nope", [1, 2]), set())


if __name__ == "__main__":
    unittest.main()
