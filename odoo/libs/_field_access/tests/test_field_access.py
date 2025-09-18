"""Unit tests for field cache access accelerator.

Tests both the Rust extension and pure-Python fallback with mock
dicts and sentinel objects — no Odoo ORM dependency.
"""

import enum
import unittest

from odoo.libs._field_access._fallback import (
    batch_cache_fill,
    batch_cache_filter,
    batch_cache_get,
    batch_cache_values,
    batch_group_ids,
    scalar_cache_get,
    sort_ids_by_values,
)


class MockSentinel(enum.Enum):
    SENTINEL = -1
    PENDING = -2


SENTINEL = MockSentinel.SENTINEL
PENDING = MockSentinel.PENDING


class _FieldAccessTestMixin:
    """Shared tests — subclassed once for Rust, once for fallback."""

    batch_cache_fill = None
    batch_cache_get = None
    batch_cache_filter = None
    batch_cache_values = None
    scalar_cache_get = None
    sort_ids_by_values = None
    batch_group_ids = None

    # --- batch_cache_fill ---

    def test_fill_all_hit(self):
        cache = {1: "a", 2: "b", 3: "c"}
        results = [{"id": 1}, {"id": 2}, {"id": 3}]
        misses = self.batch_cache_fill(cache, (1, 2, 3), results, "name", PENDING, False)
        self.assertEqual(misses, [])
        self.assertEqual(results, [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}, {"id": 3, "name": "c"}])

    def test_fill_none_becomes_none_val(self):
        cache = {1: None, 2: "x"}
        results = [{"id": 1}, {"id": 2}]
        misses = self.batch_cache_fill(cache, (1, 2), results, "name", PENDING, False)
        self.assertEqual(misses, [])
        self.assertEqual(results[0]["name"], False)
        self.assertEqual(results[1]["name"], "x")

    def test_fill_miss_returns_index(self):
        cache = {1: "a"}
        results = [{"id": 1}, {"id": 2}, {"id": 3}]
        misses = self.batch_cache_fill(cache, (1, 2, 3), results, "name", PENDING, False)
        self.assertEqual(misses, [1, 2])
        # Only id=1 filled; id=2 and id=3 not touched
        self.assertEqual(results[0]["name"], "a")
        self.assertNotIn("name", results[1])
        self.assertNotIn("name", results[2])

    def test_fill_pending_is_miss(self):
        cache = {1: PENDING, 2: "ok"}
        results = [{"id": 1}, {"id": 2}]
        misses = self.batch_cache_fill(cache, (1, 2), results, "name", PENDING, False)
        self.assertEqual(misses, [0])
        self.assertNotIn("name", results[0])
        self.assertEqual(results[1]["name"], "ok")

    def test_fill_skips_empty_dict(self):
        """Empty dicts (cleared = missing records) are skipped."""
        cache = {1: "a", 2: "b"}
        results = [{"id": 1}, {}, {"id": 3}]
        misses = self.batch_cache_fill(cache, (1, 2, 3), results, "name", PENDING, False)
        # id=2 has empty dict — skip (not a miss either)
        self.assertNotIn(1, misses)
        self.assertNotIn(1, misses)
        self.assertEqual(results[0]["name"], "a")
        self.assertEqual(results[1], {})  # untouched
        # id=3 has no cache entry → miss
        self.assertIn(2, misses)

    def test_fill_false_is_valid_value(self):
        """False is a valid cache value, not a miss."""
        cache = {1: False}
        results = [{"id": 1}]
        misses = self.batch_cache_fill(cache, (1,), results, "active", PENDING, True)
        self.assertEqual(misses, [])
        self.assertIs(results[0]["active"], False)

    def test_fill_zero_is_valid_value(self):
        """0 is a valid cache value, not a miss."""
        cache = {1: 0}
        results = [{"id": 1}]
        misses = self.batch_cache_fill(cache, (1,), results, "qty", PENDING, 0)
        self.assertEqual(misses, [])
        self.assertEqual(results[0]["qty"], 0)

    def test_fill_empty_ids(self):
        misses = self.batch_cache_fill({}, (), [], "name", PENDING, False)
        self.assertEqual(misses, [])

    # --- batch_cache_get ---

    def test_batch_get_all_hit(self):
        cache = {1: "a", 2: "b", 3: "c"}
        results, misses = self.batch_cache_get(cache, (1, 2, 3), PENDING, False)
        self.assertEqual(list(results), ["a", "b", "c"])
        self.assertEqual(list(misses), [])

    def test_batch_get_none_becomes_none_val(self):
        cache = {1: None, 2: "x"}
        results, misses = self.batch_cache_get(cache, (1, 2), PENDING, False)
        self.assertEqual(list(results), [False, "x"])
        self.assertEqual(list(misses), [])

    def test_batch_get_pending_is_miss(self):
        cache = {1: PENDING, 2: "ok"}
        results, misses = self.batch_cache_get(cache, (1, 2), PENDING, 0)
        self.assertEqual(list(results), [0, "ok"])
        self.assertEqual(list(misses), [0])

    def test_batch_get_missing_key_is_miss(self):
        cache = {1: "a"}
        results, misses = self.batch_cache_get(cache, (1, 2, 3), PENDING, "")
        self.assertEqual(list(results), ["a", "", ""])
        self.assertEqual(list(misses), [1, 2])

    def test_batch_get_empty(self):
        results, misses = self.batch_cache_get({}, (), PENDING, False)
        self.assertEqual(list(results), [])
        self.assertEqual(list(misses), [])

    def test_batch_get_false_is_valid(self):
        """False is a valid cache value, not a miss."""
        cache = {1: False}
        results, misses = self.batch_cache_get(cache, (1,), PENDING, False)
        self.assertEqual(list(results), [False])
        self.assertEqual(list(misses), [])

    def test_batch_get_zero_is_valid(self):
        """0 is a valid cache value, not a miss."""
        cache = {1: 0}
        results, misses = self.batch_cache_get(cache, (1,), PENDING, 0)
        self.assertEqual(list(results), [0])
        self.assertEqual(list(misses), [])

    def test_batch_get_all_miss(self):
        results, misses = self.batch_cache_get({}, (1, 2, 3), PENDING, -1)
        self.assertEqual(list(results), [-1, -1, -1])
        self.assertEqual(list(misses), [0, 1, 2])

    def test_batch_get_mixed(self):
        cache = {1: "a", 3: None, 5: PENDING}
        results, misses = self.batch_cache_get(cache, (1, 2, 3, 4, 5), PENDING, False)
        self.assertEqual(list(results), ["a", False, False, False, False])
        self.assertEqual(list(misses), [1, 3, 4])

    # --- batch_cache_filter ---

    def test_filter_truthy_values(self):
        cache = {1: "yes", 2: "", 3: 42, 4: 0, 5: None}
        passing, misses = self.batch_cache_filter(cache, (1, 2, 3, 4, 5), PENDING)
        self.assertEqual(list(passing), [1, 3])
        self.assertEqual(list(misses), [])

    def test_filter_pending_is_miss(self):
        cache = {1: PENDING, 2: "ok"}
        passing, misses = self.batch_cache_filter(cache, (1, 2), PENDING)
        self.assertEqual(list(passing), [2])
        self.assertEqual(list(misses), [0])

    def test_filter_missing_key_is_miss(self):
        cache = {1: "ok"}
        passing, misses = self.batch_cache_filter(cache, (1, 2), PENDING)
        self.assertEqual(list(passing), [1])
        self.assertEqual(list(misses), [1])

    def test_filter_empty(self):
        passing, misses = self.batch_cache_filter({}, (), PENDING)
        self.assertEqual(list(passing), [])
        self.assertEqual(list(misses), [])

    def test_filter_all_falsy(self):
        cache = {1: 0, 2: "", 3: False, 4: None}
        passing, misses = self.batch_cache_filter(cache, (1, 2, 3, 4), PENDING)
        self.assertEqual(list(passing), [])
        self.assertEqual(list(misses), [])

    def test_filter_all_truthy(self):
        cache = {1: "a", 2: 1, 3: True}
        passing, misses = self.batch_cache_filter(cache, (1, 2, 3), PENDING)
        self.assertEqual(list(passing), [1, 2, 3])
        self.assertEqual(list(misses), [])

    # --- batch_cache_values ---

    def test_values_all_hit(self):
        cache = {1: "a", 2: "b", 3: "c"}
        result = self.batch_cache_values(cache, (1, 2, 3), PENDING)
        self.assertEqual(list(result), ["a", "b", "c"])

    def test_values_miss_returns_none(self):
        cache = {1: "a"}
        result = self.batch_cache_values(cache, (1, 2), PENDING)
        self.assertIsNone(result)

    def test_values_pending_returns_none(self):
        cache = {1: PENDING, 2: "ok"}
        result = self.batch_cache_values(cache, (1, 2), PENDING)
        self.assertIsNone(result)

    def test_values_empty(self):
        result = self.batch_cache_values({}, (), PENDING)
        self.assertEqual(list(result), [])

    def test_values_none_is_valid(self):
        """None is a valid cache value — not a miss."""
        cache = {1: None, 2: "x"}
        result = self.batch_cache_values(cache, (1, 2), PENDING)
        self.assertEqual(list(result), [None, "x"])

    def test_values_false_is_valid(self):
        """False is a valid cache value — not a miss."""
        cache = {1: False, 2: 0}
        result = self.batch_cache_values(cache, (1, 2), PENDING)
        self.assertEqual(list(result), [False, 0])

    def test_values_early_bailout(self):
        """Should bail on first miss, not process remaining IDs."""
        cache = {1: "a"}  # id 2 missing
        result = self.batch_cache_values(cache, (1, 2, 3), PENDING)
        self.assertIsNone(result)

    # --- scalar_cache_get ---

    def test_scalar_hit(self):
        field = object()
        env_dict = {"_field_cache_memo": {field: {42: "value"}}}
        result = self.scalar_cache_get(env_dict, field, 42, PENDING, SENTINEL)
        self.assertEqual(result, "value")

    def test_scalar_miss_no_memo(self):
        result = self.scalar_cache_get({}, "f", 42, PENDING, SENTINEL)
        self.assertIs(result, SENTINEL)

    def test_scalar_miss_no_field(self):
        env_dict = {"_field_cache_memo": {}}
        result = self.scalar_cache_get(env_dict, "f", 42, PENDING, SENTINEL)
        self.assertIs(result, SENTINEL)

    def test_scalar_miss_no_id(self):
        field = object()
        env_dict = {"_field_cache_memo": {field: {}}}
        result = self.scalar_cache_get(env_dict, field, 42, PENDING, SENTINEL)
        self.assertIs(result, SENTINEL)

    def test_scalar_pending_returns_sentinel(self):
        field = object()
        env_dict = {"_field_cache_memo": {field: {42: PENDING}}}
        result = self.scalar_cache_get(env_dict, field, 42, PENDING, SENTINEL)
        self.assertIs(result, SENTINEL)

    def test_scalar_none_is_valid(self):
        """None is a valid cache value, not a miss."""
        field = object()
        env_dict = {"_field_cache_memo": {field: {42: None}}}
        result = self.scalar_cache_get(env_dict, field, 42, PENDING, SENTINEL)
        self.assertIsNone(result)

    def test_scalar_false_is_valid(self):
        """False is a valid cache value, not a miss."""
        field = object()
        env_dict = {"_field_cache_memo": {field: {42: False}}}
        result = self.scalar_cache_get(env_dict, field, 42, PENDING, SENTINEL)
        self.assertIs(result, False)

    def test_scalar_zero_is_valid(self):
        field = object()
        env_dict = {"_field_cache_memo": {field: {42: 0}}}
        result = self.scalar_cache_get(env_dict, field, 42, PENDING, SENTINEL)
        self.assertEqual(result, 0)


    # --- sort_ids_by_values ---

    def test_sort_basic_asc(self):
        ids = (3, 1, 2)
        values = ["c", "a", "b"]
        result = self.sort_ids_by_values(ids, values, False)
        self.assertEqual(result, (1, 2, 3))

    def test_sort_basic_desc(self):
        ids = (3, 1, 2)
        values = ["c", "a", "b"]
        result = self.sort_ids_by_values(ids, values, True)
        self.assertEqual(result, (3, 2, 1))

    def test_sort_integers(self):
        ids = (10, 20, 30, 40)
        values = [40, 10, 30, 20]
        result = self.sort_ids_by_values(ids, values, False)
        self.assertEqual(result, (20, 40, 30, 10))

    def test_sort_stable_equal_values(self):
        """Equal values preserve original order (stable sort)."""
        ids = (1, 2, 3)
        values = ["x", "x", "x"]
        result = self.sort_ids_by_values(ids, values, False)
        self.assertEqual(result, (1, 2, 3))

    def test_sort_single_element(self):
        result = self.sort_ids_by_values((5,), ["z"], False)
        self.assertEqual(result, (5,))

    def test_sort_empty(self):
        result = self.sort_ids_by_values((), [], False)
        self.assertEqual(result, ())

    def test_sort_null_high_false_sorts_nulls_first(self):
        """null_high=False → None/False sort before non-nulls in ASC."""
        ids = (1, 2, 3)
        values = ["b", None, "a"]
        result = self.sort_ids_by_values(ids, values, False, null_high=False)
        self.assertEqual(result, (2, 3, 1))  # None first, then "a", "b"

    def test_sort_null_high_true_sorts_nulls_last(self):
        """null_high=True → None/False sort after non-nulls in ASC."""
        ids = (1, 2, 3)
        values = ["b", None, "a"]
        result = self.sort_ids_by_values(ids, values, False, null_high=True)
        self.assertEqual(result, (3, 1, 2))  # "a", "b", then None last

    def test_sort_false_treated_as_null(self):
        """False is treated as null like None."""
        ids = (1, 2, 3)
        values = ["b", False, "a"]
        result = self.sort_ids_by_values(ids, values, False, null_high=False)
        self.assertEqual(result, (2, 3, 1))

    def test_sort_null_high_none_ignores_none(self):
        """null_high=None does not treat None specially."""
        ids = (1, 2)
        values = [2, 1]
        result = self.sort_ids_by_values(ids, values, False, null_high=None)
        self.assertEqual(result, (2, 1))

    # --- batch_group_ids ---

    def test_group_basic(self):
        ids = (1, 2, 3, 4)
        values = ["a", "b", "a", "b"]
        result = self.batch_group_ids(ids, values)
        self.assertEqual(set(result.keys()), {"a", "b"})
        self.assertEqual(sorted(result["a"]), [1, 3])
        self.assertEqual(sorted(result["b"]), [2, 4])

    def test_group_single_group(self):
        ids = (1, 2, 3)
        values = ["x", "x", "x"]
        result = self.batch_group_ids(ids, values)
        self.assertEqual(list(result.keys()), ["x"])
        self.assertEqual(result["x"], [1, 2, 3])

    def test_group_all_unique(self):
        ids = (1, 2, 3)
        values = ["a", "b", "c"]
        result = self.batch_group_ids(ids, values)
        self.assertEqual(result["a"], [1])
        self.assertEqual(result["b"], [2])
        self.assertEqual(result["c"], [3])

    def test_group_preserves_order_within_group(self):
        ids = (3, 1, 4, 1, 5)
        values = ["x", "y", "x", "y", "x"]
        result = self.batch_group_ids(ids, values)
        self.assertEqual(result["x"], [3, 4, 5])
        self.assertEqual(result["y"], [1, 1])

    def test_group_integer_keys(self):
        ids = (10, 20, 30)
        values = [1, 2, 1]
        result = self.batch_group_ids(ids, values)
        self.assertEqual(result[1], [10, 30])
        self.assertEqual(result[2], [20])

    def test_group_none_key(self):
        """None is a valid group key."""
        ids = (1, 2, 3)
        values = [None, "a", None]
        result = self.batch_group_ids(ids, values)
        self.assertEqual(result[None], [1, 3])
        self.assertEqual(result["a"], [2])

    def test_group_empty(self):
        result = self.batch_group_ids((), [])
        self.assertEqual(result, {})


class TestFallback(_FieldAccessTestMixin, unittest.TestCase):
    """Test pure-Python fallback implementations."""

    @classmethod
    def setUpClass(cls):
        cls.batch_cache_fill = staticmethod(batch_cache_fill)
        cls.batch_cache_get = staticmethod(batch_cache_get)
        cls.batch_cache_filter = staticmethod(batch_cache_filter)
        cls.batch_cache_values = staticmethod(batch_cache_values)
        cls.scalar_cache_get = staticmethod(scalar_cache_get)
        cls.sort_ids_by_values = staticmethod(sort_ids_by_values)
        cls.batch_group_ids = staticmethod(batch_group_ids)


class TestAccelerated(_FieldAccessTestMixin, unittest.TestCase):
    """Test Rust extension — skipped if not installed.

    scalar_cache_get always uses the Python fallback (PyO3 boundary
    overhead exceeds savings on the hit path), so only batch functions
    are imported from Rust.
    """

    @classmethod
    def setUpClass(cls):
        try:
            from odoo_rust import (
                batch_cache_fill,
                batch_cache_filter,
                batch_cache_get,
                batch_cache_values,
                batch_group_ids,
                sort_ids_by_values,
            )
        except ImportError:
            raise unittest.SkipTest("odoo_rust Rust extension not installed")
        cls.batch_cache_fill = staticmethod(batch_cache_fill)
        cls.batch_cache_get = staticmethod(batch_cache_get)
        cls.batch_cache_filter = staticmethod(batch_cache_filter)
        cls.batch_cache_values = staticmethod(batch_cache_values)
        cls.scalar_cache_get = staticmethod(scalar_cache_get)
        cls.sort_ids_by_values = staticmethod(sort_ids_by_values)
        cls.batch_group_ids = staticmethod(batch_group_ids)


if __name__ == "__main__":
    unittest.main()
