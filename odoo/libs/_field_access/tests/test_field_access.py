import enum
import sys
import unittest
from datetime import date, datetime
from typing import TYPE_CHECKING

import pytest

from odoo.libs._field_access._fallback import (
    batch_cache_fill,
    batch_cache_filter,
    batch_cache_get,
    batch_group_ids,
    scalar_cache_get,
    sort_ids_by_cache,
    to_prefetch_ids,
)

odoo_rust = pytest.importorskip(
    "odoo_rust", exc_type=ImportError
)  # a parity test needs both sides
_rust_batch_cache_fill = odoo_rust.batch_cache_fill
_rust_batch_cache_filter = odoo_rust.batch_cache_filter
_rust_batch_cache_get = odoo_rust.batch_cache_get
_rust_batch_group_ids = odoo_rust.batch_group_ids
_rust_sort_ids_by_cache = odoo_rust.sort_ids_by_cache
_rust_to_prefetch_ids = odoo_rust.to_prefetch_ids

if TYPE_CHECKING:
    from collections.abc import Callable


class MockSentinel(enum.Enum):
    SENTINEL = -1
    PENDING = -2


SENTINEL = MockSentinel.SENTINEL
PENDING = MockSentinel.PENDING


class _FakeNewId:
    __slots__ = ()

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "<NewId>"


if TYPE_CHECKING:
    _MixinBase = unittest.TestCase
else:
    _MixinBase = object


class _FieldAccessTestMixin(_MixinBase):
    batch_cache_fill: Callable
    batch_cache_get: Callable
    batch_cache_filter: Callable
    scalar_cache_get: Callable
    sort_ids_by_cache: Callable
    batch_group_ids: Callable
    to_prefetch_ids: Callable

    def test_prefetch_basic(self) -> None:
        self.assertEqual(self.to_prefetch_ids(1, (1, 2, 3), {}, 10), (1, 2, 3))

    def test_prefetch_record_id_always_first(self) -> None:
        self.assertEqual(self.to_prefetch_ids(7, (2, 3), {}, 10), (7, 2, 3))

    def test_prefetch_skips_cached(self) -> None:
        self.assertEqual(self.to_prefetch_ids(1, (2, 3, 4), {3: "v"}, 10), (1, 2, 4))

    def test_prefetch_record_id_kept_even_when_cached(self) -> None:
        self.assertEqual(self.to_prefetch_ids(1, (2,), {1: "v"}, 10), (1, 2))

    def test_prefetch_dedups(self) -> None:
        self.assertEqual(self.to_prefetch_ids(1, (2, 2, 3, 2), {}, 10), (1, 2, 3))

    def test_prefetch_dedups_against_record_id(self) -> None:
        self.assertEqual(self.to_prefetch_ids(5, (5, 6, 5), {}, 10), (5, 6))

    def test_prefetch_respects_max(self) -> None:
        self.assertEqual(self.to_prefetch_ids(1, (2, 3, 4, 5), {}, 3), (1, 2, 3))

    def test_prefetch_max_one(self) -> None:
        self.assertEqual(self.to_prefetch_ids(1, (2, 3), {}, 1), (1,))

    def test_prefetch_empty_prefetch_ids(self) -> None:
        self.assertEqual(self.to_prefetch_ids(1, (), {}, 10), (1,))

    def test_prefetch_new_record_returns_none(self) -> None:
        self.assertIsNone(self.to_prefetch_ids(0, (1, 2), {}, 10))
        self.assertIsNone(self.to_prefetch_ids(_FakeNewId(), (1, 2), {}, 10))

    def test_prefetch_negative_record_id_returns_none(self) -> None:
        self.assertIsNone(self.to_prefetch_ids(-1, (1, 2), {}, 10))

    def test_prefetch_drops_non_positive_ids(self) -> None:
        self.assertEqual(self.to_prefetch_ids(1, (0, -5, 2), {}, 10), (1, 2))

    def test_prefetch_drops_non_int_ids(self) -> None:
        self.assertEqual(
            self.to_prefetch_ids(1, ("7", _FakeNewId(), 2), {}, 10), (1, 2)
        )

    def test_prefetch_drops_ids_beyond_i64(self) -> None:
        self.assertEqual(self.to_prefetch_ids(1, (2**63, 2**70, 2), {}, 10), (1, 2))

    def test_fill_all_hit(self) -> None:
        cache = {1: "a", 2: "b", 3: "c"}
        results = [{"id": 1}, {"id": 2}, {"id": 3}]
        misses = self.batch_cache_fill(
            cache, (1, 2, 3), results, "name", PENDING, False
        )
        self.assertEqual(misses, [])
        self.assertEqual(
            results,
            [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}, {"id": 3, "name": "c"}],
        )

    def test_fill_none_becomes_none_val(self) -> None:
        cache = {1: None, 2: "x"}
        results = [{"id": 1}, {"id": 2}]
        misses = self.batch_cache_fill(cache, (1, 2), results, "name", PENDING, False)
        self.assertEqual(misses, [])
        self.assertEqual(results[0]["name"], False)
        self.assertEqual(results[1]["name"], "x")

    def test_fill_miss_returns_index(self) -> None:
        cache = {1: "a"}
        results = [{"id": 1}, {"id": 2}, {"id": 3}]
        misses = self.batch_cache_fill(
            cache, (1, 2, 3), results, "name", PENDING, False
        )
        self.assertEqual(misses, [1, 2])
        self.assertEqual(results[0]["name"], "a")
        self.assertNotIn("name", results[1])
        self.assertNotIn("name", results[2])

    def test_fill_pending_is_miss(self) -> None:
        cache = {1: PENDING, 2: "ok"}
        results = [{"id": 1}, {"id": 2}]
        misses = self.batch_cache_fill(cache, (1, 2), results, "name", PENDING, False)
        self.assertEqual(misses, [0])
        self.assertNotIn("name", results[0])
        self.assertEqual(results[1]["name"], "ok")

    def test_fill_skips_empty_dict(self) -> None:
        cache = {1: "a", 2: "b"}
        results = [{"id": 1}, {}, {"id": 3}]
        misses = self.batch_cache_fill(
            cache, (1, 2, 3), results, "name", PENDING, False
        )
        self.assertNotIn(1, misses)
        self.assertNotIn(1, misses)
        self.assertEqual(results[0]["name"], "a")
        self.assertEqual(results[1], {})
        self.assertIn(2, misses)

    def test_fill_false_is_valid_value(self) -> None:
        cache = {1: False}
        results = [{"id": 1}]
        misses = self.batch_cache_fill(cache, (1,), results, "active", PENDING, True)
        self.assertEqual(misses, [])
        self.assertIs(results[0]["active"], False)

    def test_fill_zero_is_valid_value(self) -> None:
        cache = {1: 0}
        results = [{"id": 1}]
        misses = self.batch_cache_fill(cache, (1,), results, "qty", PENDING, 0)
        self.assertEqual(misses, [])
        self.assertEqual(results[0]["qty"], 0)

    def test_fill_empty_ids(self) -> None:
        misses = self.batch_cache_fill({}, (), [], "name", PENDING, False)
        self.assertEqual(misses, [])

    def test_prefetch_non_positive_budget_returns_the_record_alone(self) -> None:
        for budget in (0, -1):
            self.assertEqual(
                self.to_prefetch_ids(1, (2, 3), {}, budget), (1,), f"budget={budget}"
            )

    def test_fill_writes_through_a_dict_subclass(self) -> None:
        class Subclass(dict):
            pass

        results = [Subclass(id=1)]
        misses = self.batch_cache_fill({1: "v"}, (1,), results, "f", PENDING, None)
        self.assertEqual(misses, [])
        self.assertEqual(dict(results[0]), {"id": 1, "f": "v"})

    def test_fill_empty_dict_subclass_is_still_skipped(self) -> None:
        class Subclass(dict):
            pass

        results = [Subclass()]
        self.assertEqual(
            self.batch_cache_fill({1: "v"}, (1,), results, "f", PENDING, None), []
        )
        self.assertEqual(dict(results[0]), {})

    def test_fill_non_mapping_raises(self) -> None:
        with self.assertRaises(TypeError):
            self.batch_cache_fill({1: "v"}, (1,), [[9]], "f", PENDING, None)

    def test_fill_length_mismatch_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.batch_cache_fill({}, (1, 2, 3), [{"id": 1}], "name", PENDING, False)

    def test_group_unhashable_value_raises(self) -> None:
        with self.assertRaises(TypeError):
            self.batch_group_ids((1,), [[]])

    def test_group_ids_length_mismatch_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.batch_group_ids((1, 2, 3, 4, 5), ["a"])

    def test_batch_get_all_hit(self) -> None:
        cache = {1: "a", 2: "b", 3: "c"}
        results, misses = self.batch_cache_get(cache, (1, 2, 3), PENDING, False)
        self.assertEqual(list(results), ["a", "b", "c"])
        self.assertEqual(list(misses), [])

    def test_batch_get_none_becomes_none_val(self) -> None:
        cache = {1: None, 2: "x"}
        results, misses = self.batch_cache_get(cache, (1, 2), PENDING, False)
        self.assertEqual(list(results), [False, "x"])
        self.assertEqual(list(misses), [])

    def test_batch_get_pending_is_miss(self) -> None:
        cache = {1: PENDING, 2: "ok"}
        results, misses = self.batch_cache_get(cache, (1, 2), PENDING, 0)
        self.assertEqual(list(results), [0, "ok"])
        self.assertEqual(list(misses), [0])

    def test_batch_get_missing_key_is_miss(self) -> None:
        cache = {1: "a"}
        results, misses = self.batch_cache_get(cache, (1, 2, 3), PENDING, "")
        self.assertEqual(list(results), ["a", "", ""])
        self.assertEqual(list(misses), [1, 2])

    def test_batch_get_empty(self) -> None:
        results, misses = self.batch_cache_get({}, (), PENDING, False)
        self.assertEqual(list(results), [])
        self.assertEqual(list(misses), [])

    def test_batch_get_false_is_valid(self) -> None:
        cache = {1: False}
        results, misses = self.batch_cache_get(cache, (1,), PENDING, False)
        self.assertEqual(list(results), [False])
        self.assertEqual(list(misses), [])

    def test_batch_get_zero_is_valid(self) -> None:
        cache = {1: 0}
        results, misses = self.batch_cache_get(cache, (1,), PENDING, 0)
        self.assertEqual(list(results), [0])
        self.assertEqual(list(misses), [])

    def test_batch_get_all_miss(self) -> None:
        results, misses = self.batch_cache_get({}, (1, 2, 3), PENDING, -1)
        self.assertEqual(list(results), [-1, -1, -1])
        self.assertEqual(list(misses), [0, 1, 2])

    def test_batch_get_mixed(self) -> None:
        cache = {1: "a", 3: None, 5: PENDING}
        results, misses = self.batch_cache_get(cache, (1, 2, 3, 4, 5), PENDING, False)
        self.assertEqual(list(results), ["a", False, False, False, False])
        self.assertEqual(list(misses), [1, 3, 4])

    def test_filter_truthy_values(self) -> None:
        cache = {1: "yes", 2: "", 3: 42, 4: 0, 5: None}
        passing, misses = self.batch_cache_filter(cache, (1, 2, 3, 4, 5), PENDING)
        self.assertEqual(list(passing), [1, 3])
        self.assertEqual(list(misses), [])

    def test_filter_pending_is_miss(self) -> None:
        cache = {1: PENDING, 2: "ok"}
        passing, misses = self.batch_cache_filter(cache, (1, 2), PENDING)
        self.assertEqual(list(passing), [2])
        self.assertEqual(list(misses), [0])

    def test_filter_missing_key_is_miss(self) -> None:
        cache = {1: "ok"}
        passing, misses = self.batch_cache_filter(cache, (1, 2), PENDING)
        self.assertEqual(list(passing), [1])
        self.assertEqual(list(misses), [1])

    def test_filter_empty(self) -> None:
        passing, misses = self.batch_cache_filter({}, (), PENDING)
        self.assertEqual(list(passing), [])
        self.assertEqual(list(misses), [])

    def test_filter_all_falsy(self) -> None:
        cache = {1: 0, 2: "", 3: False, 4: None}
        passing, misses = self.batch_cache_filter(cache, (1, 2, 3, 4), PENDING)
        self.assertEqual(list(passing), [])
        self.assertEqual(list(misses), [])

    def test_filter_all_truthy(self) -> None:
        cache = {1: "a", 2: 1, 3: True}
        passing, misses = self.batch_cache_filter(cache, (1, 2, 3), PENDING)
        self.assertEqual(list(passing), [1, 2, 3])
        self.assertEqual(list(misses), [])

    def test_scalar_hit(self) -> None:
        field = object()
        env_dict = {"_field_cache_memo": {field: {42: "value"}}}
        result = self.scalar_cache_get(env_dict, field, 42, PENDING, SENTINEL)
        self.assertEqual(result, "value")

    def test_scalar_miss_no_memo(self) -> None:
        result = self.scalar_cache_get({}, "f", 42, PENDING, SENTINEL)
        self.assertIs(result, SENTINEL)

    def test_scalar_miss_no_field(self) -> None:
        env_dict: dict = {"_field_cache_memo": {}}
        result = self.scalar_cache_get(env_dict, "f", 42, PENDING, SENTINEL)
        self.assertIs(result, SENTINEL)

    def test_scalar_miss_no_id(self) -> None:
        field = object()
        env_dict: dict = {"_field_cache_memo": {field: {}}}
        result = self.scalar_cache_get(env_dict, field, 42, PENDING, SENTINEL)
        self.assertIs(result, SENTINEL)

    def test_scalar_pending_returns_sentinel(self) -> None:
        field = object()
        env_dict = {"_field_cache_memo": {field: {42: PENDING}}}
        result = self.scalar_cache_get(env_dict, field, 42, PENDING, SENTINEL)
        self.assertIs(result, SENTINEL)

    def test_scalar_none_is_valid(self) -> None:
        field = object()
        env_dict = {"_field_cache_memo": {field: {42: None}}}
        result = self.scalar_cache_get(env_dict, field, 42, PENDING, SENTINEL)
        self.assertIsNone(result)

    def test_scalar_false_is_valid(self) -> None:
        field = object()
        env_dict = {"_field_cache_memo": {field: {42: False}}}
        result = self.scalar_cache_get(env_dict, field, 42, PENDING, SENTINEL)
        self.assertIs(result, False)

    def test_scalar_zero_is_valid(self) -> None:
        field = object()
        env_dict = {"_field_cache_memo": {field: {42: 0}}}
        result = self.scalar_cache_get(env_dict, field, 42, PENDING, SENTINEL)
        self.assertEqual(result, 0)

    def _sort(self, ids, values, reverse, null_high=True):
        cache = dict(zip(ids, values, strict=True))
        return self.sort_ids_by_cache(cache, ids, PENDING, reverse, null_high)

    def test_sort_basic_asc(self) -> None:
        self.assertEqual(self._sort((3, 1, 2), ["c", "a", "b"], False), (1, 2, 3))

    def test_sort_basic_desc(self) -> None:
        self.assertEqual(self._sort((3, 1, 2), ["c", "a", "b"], True), (3, 2, 1))

    def test_sort_integers(self) -> None:
        self.assertEqual(
            self._sort((10, 20, 30, 40), [40, 10, 30, 20], False), (20, 40, 30, 10)
        )

    def test_sort_stable_equal_values(self) -> None:
        self.assertEqual(self._sort((1, 2, 3), ["x", "x", "x"], False), (1, 2, 3))

    def test_sort_single_element(self) -> None:
        self.assertEqual(self._sort((5,), ["z"], False), (5,))

    def test_sort_empty(self) -> None:
        self.assertEqual(self._sort((), [], False), ())

    def test_sort_null_high_false_sorts_nulls_first(self) -> None:
        self.assertEqual(
            self._sort((1, 2, 3), ["b", None, "a"], False, null_high=False), (2, 3, 1)
        )

    def test_sort_null_high_true_sorts_nulls_last(self) -> None:
        self.assertEqual(
            self._sort((1, 2, 3), ["b", None, "a"], False, null_high=True), (3, 1, 2)
        )

    def test_sort_false_treated_as_null(self) -> None:
        self.assertEqual(
            self._sort((1, 2, 3), ["b", False, "a"], False, null_high=False), (2, 3, 1)
        )

    def test_sort_cache_basic_asc(self) -> None:
        ids = (3, 1, 2)
        cache = {3: "c", 1: "a", 2: "b"}
        result = self.sort_ids_by_cache(cache, ids, PENDING, False, True)
        self.assertEqual(result, (1, 2, 3))

    def test_sort_cache_desc(self) -> None:
        ids = (3, 1, 2)
        cache = {3: "c", 1: "a", 2: "b"}
        result = self.sort_ids_by_cache(cache, ids, PENDING, True, True)
        self.assertEqual(result, (3, 2, 1))

    def test_sort_cache_null_high_true(self) -> None:
        ids = (1, 2, 3)
        cache = {1: "b", 2: None, 3: "a"}
        result = self.sort_ids_by_cache(cache, ids, PENDING, False, null_high=True)
        self.assertEqual(result, (3, 1, 2))

    def test_sort_cache_single_and_empty(self) -> None:
        self.assertEqual(
            self.sort_ids_by_cache({5: "z"}, (5,), PENDING, False, True), (5,)
        )
        self.assertEqual(self.sort_ids_by_cache({}, (), PENDING, False, True), ())

    def test_sort_cache_miss_returns_none(self) -> None:
        ids = (1, 2, 3)
        cache = {1: "a", 3: "c"}
        self.assertIsNone(self.sort_ids_by_cache(cache, ids, PENDING, False, True))

    def test_sort_cache_pending_returns_none(self) -> None:
        ids = (1, 2, 3)
        cache = {1: "a", 2: PENDING, 3: "c"}
        self.assertIsNone(self.sort_ids_by_cache(cache, ids, PENDING, False, True))

    def test_group_basic(self) -> None:
        ids = (1, 2, 3, 4)
        values = ["a", "b", "a", "b"]
        result = self.batch_group_ids(ids, values)
        self.assertEqual(set(result.keys()), {"a", "b"})
        self.assertEqual(sorted(result["a"]), [1, 3])
        self.assertEqual(sorted(result["b"]), [2, 4])

    def test_group_single_group(self) -> None:
        ids = (1, 2, 3)
        values = ["x", "x", "x"]
        result = self.batch_group_ids(ids, values)
        self.assertEqual(list(result.keys()), ["x"])
        self.assertEqual(result["x"], [1, 2, 3])

    def test_group_all_unique(self) -> None:
        ids = (1, 2, 3)
        values = ["a", "b", "c"]
        result = self.batch_group_ids(ids, values)
        self.assertEqual(result["a"], [1])
        self.assertEqual(result["b"], [2])
        self.assertEqual(result["c"], [3])

    def test_group_preserves_order_within_group(self) -> None:
        ids = (3, 1, 4, 1, 5)
        values = ["x", "y", "x", "y", "x"]
        result = self.batch_group_ids(ids, values)
        self.assertEqual(result["x"], [3, 4, 5])
        self.assertEqual(result["y"], [1, 1])

    def test_group_integer_keys(self) -> None:
        ids = (10, 20, 30)
        values = [1, 2, 1]
        result = self.batch_group_ids(ids, values)
        self.assertEqual(result[1], [10, 30])
        self.assertEqual(result[2], [20])

    def test_group_none_key(self) -> None:
        ids = (1, 2, 3)
        values = [None, "a", None]
        result = self.batch_group_ids(ids, values)
        self.assertEqual(result[None], [1, 3])
        self.assertEqual(result["a"], [2])

    def test_group_empty(self) -> None:
        result = self.batch_group_ids((), [])
        self.assertEqual(result, {})


class TestFallback(_FieldAccessTestMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.batch_cache_fill = staticmethod(batch_cache_fill)
        cls.batch_cache_get = staticmethod(batch_cache_get)
        cls.batch_cache_filter = staticmethod(batch_cache_filter)
        cls.scalar_cache_get = staticmethod(scalar_cache_get)
        cls.sort_ids_by_cache = staticmethod(sort_ids_by_cache)
        cls.batch_group_ids = staticmethod(batch_group_ids)
        cls.to_prefetch_ids = staticmethod(to_prefetch_ids)


class TestAccelerated(_FieldAccessTestMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.batch_cache_fill = staticmethod(_rust_batch_cache_fill)
        cls.batch_cache_get = staticmethod(_rust_batch_cache_get)
        cls.batch_cache_filter = staticmethod(_rust_batch_cache_filter)
        cls.scalar_cache_get = staticmethod(scalar_cache_get)
        cls.sort_ids_by_cache = staticmethod(_rust_sort_ids_by_cache)
        cls.batch_group_ids = staticmethod(_rust_batch_group_ids)
        cls.to_prefetch_ids = staticmethod(_rust_to_prefetch_ids)


class TestAcceleratedMemorySafety(unittest.TestCase):
    def test_a_reentrant_bool_that_shrinks_results_is_refused(self) -> None:
        class Evil(dict):
            target: list | None = None

            def __bool__(self) -> bool:
                if Evil.target is not None:
                    del Evil.target[2:]
                return True

        ids = (1, 2, 3, 4, 5)
        cache = {i: f"v{i}" for i in ids}
        results: list = [Evil(id=i) for i in ids]
        Evil.target = results
        try:
            with self.assertRaises(ValueError):
                _rust_batch_cache_fill(cache, ids, results, "f", PENDING, None)
        finally:
            Evil.target = None

    def test_a_reentrant_hash_that_shrinks_values_is_refused(self) -> None:
        class Evil:
            target: list | None = None

            def __hash__(self) -> int:
                if Evil.target is not None:
                    del Evil.target[1:]
                return 1

            def __eq__(self, other: object) -> bool:
                return self is other

        values: list = [Evil(), "b", "c", "d", "e"]
        ids = tuple(range(1, len(values) + 1))
        Evil.target = values
        try:
            with self.assertRaises(ValueError):
                _rust_batch_group_ids(ids, values)
        finally:
            Evil.target = None

    def test_a_group_key_freed_by_its_own_hash_survives_the_insert(self) -> None:
        class Suicidal:
            target: list | None = None

            def __hash__(self) -> int:
                if Suicidal.target is not None:
                    Suicidal.target[0] = None
                return 7

            def __eq__(self, other: object) -> bool:
                return self is other

        values: list = [Suicidal()]
        Suicidal.target = values
        try:
            result = _rust_batch_group_ids((1,), values)
        finally:
            Suicidal.target = None
        self.assertEqual(list(result.values()), [[1]])

    def test_a_failing_group_releases_the_key_it_borrowed(self) -> None:
        key: list = ["unhashable"]
        before = sys.getrefcount(key)
        for _ in range(100):
            with self.assertRaises(TypeError):
                _rust_batch_group_ids((1,), [key])
        self.assertEqual(
            sys.getrefcount(key),
            before,
            "batch_group_ids leaked a reference to the group key on its error path",
        )


class TestSortDifferential(unittest.TestCase):
    @staticmethod
    def _capture(fn, *args, **kw):
        try:
            return ("ok", fn(*args, **kw))
        except Exception as exc:
            return ("raise", type(exc).__name__)

    def _assert_cache_match(self, values) -> None:
        ids = tuple(range(1, len(values) + 1))
        cache = dict(zip(ids, values, strict=True))
        for reverse in (False, True):
            for null_high in (False, True):
                rust = self._capture(
                    _rust_sort_ids_by_cache, cache, ids, PENDING, reverse, null_high
                )
                py = self._capture(
                    sort_ids_by_cache, cache, ids, PENDING, reverse, null_high
                )
                self.assertEqual(
                    rust, py, msg=f"values={values!r} {reverse=} {null_high=}"
                )

    _assert_values_match = _assert_cache_match

    def test_diff_big_ints(self) -> None:
        self._assert_values_match([2**63, 2**63 + 1, 1, 2**70, -(2**63) - 5])
        self._assert_cache_match([2**63, 2**63 + 1, 1, 2**70])

    def test_diff_floats_signed_zero(self) -> None:
        self._assert_values_match([1.0, -0.0, 0.0, 2.0, -1.5])
        self._assert_cache_match([1.0, -0.0, 0.0, 2.0, -1.5])

    def test_diff_floats_nan(self) -> None:
        self._assert_values_match([1.0, float("nan"), 2.0, 0.0, float("nan")])

    def test_diff_dates(self) -> None:
        self._assert_values_match(
            [date(2021, 1, 1), date(2020, 6, 15), date(2022, 3, 3)]
        )
        self._assert_cache_match(
            [date(2021, 1, 1), date(2020, 6, 15), date(2022, 3, 3)]
        )

    def test_diff_datetimes(self) -> None:
        self._assert_values_match(
            [
                datetime(2021, 1, 1, 12, 0),
                datetime(2021, 1, 1, 9, 0),
                datetime(2020, 12, 31, 23, 59),
            ]
        )

    def test_diff_mixed_date_datetime(self) -> None:
        values = [date(2021, 1, 2), datetime(2021, 1, 1, 12, 0), date(2021, 1, 1)]
        with self.assertRaises(TypeError):
            sorted(values)
        self._assert_values_match(values)

    def test_diff_datetime_subclass_of_date_is_not_a_date_column(self) -> None:
        self._assert_values_match(
            [datetime(2021, 1, 2), datetime(2021, 1, 1, 12, 0), datetime(2021, 1, 1)]
        )
        self._assert_values_match([date(2021, 1, 2), date(2021, 1, 1)])

    def test_diff_mixed_int_str(self) -> None:
        self._assert_values_match([3, "a", 1])

    def test_diff_non_ascii(self) -> None:
        self._assert_values_match(["é", "a", "ñ", "z", "😀", "b", "Z"])
        self._assert_cache_match(["é", "a", "ñ", "z", "😀", "b", "Z"])


if __name__ == "__main__":
    unittest.main()


class TestBoolIdParityWithRust(unittest.TestCase):
    def test_a_bool_record_id_is_accepted_by_both(self):
        self.assertEqual(_rust_to_prefetch_ids(True, (), {}, 10), (True,))
        self.assertEqual(to_prefetch_ids(True, (), {}, 10), (True,))

    def test_a_bool_inside_prefetch_ids_is_skipped_by_both(self):
        self.assertEqual(_rust_to_prefetch_ids(1, (True, 2), {}, 10), (1, 2))
        self.assertEqual(to_prefetch_ids(1, (True, 2), {}, 10), (1, 2))

    def test_false_is_rejected_by_both(self):
        self.assertIsNone(_rust_to_prefetch_ids(False, (), {}, 10))
        self.assertIsNone(to_prefetch_ids(False, (), {}, 10))
