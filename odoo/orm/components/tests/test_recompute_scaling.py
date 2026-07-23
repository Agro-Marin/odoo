"""RecomputeScheduler.process_entry cost/semantics pins (no Odoo, no DB).

Audit finding: the recursive stored-computed branch built a merged ``known``
set (``marked | to_recompute``) per trigger entry — O(|pending|) with a
100k-id pending map (~500 ms per 500 entries, see the audit's
``bench_process_entry`` script). The fix is two left-iterating subtractions
(identical algebra); the non-stored branch's ``ids & cached_ids`` similarly
iterated the whole cached-id view (right operand) in cache order, and now
iterates the entry's ids, preserving recordset order end to end.

These tests pin the semantics of the rewritten branches (the O() claims are
covered by the benchmark script, not timing asserts).
"""

import unittest

from odoo.orm.components.compute import ComputeEngine
from odoo.orm.components.recompute import RecomputeScheduler
from odoo.tools import OrderedSet


class _MockField:
    __slots__ = ("is_stored_computed", "name", "recursive")

    def __init__(
        self, name: str, *, stored_computed: bool = False, recursive: bool = False
    ) -> None:
        self.name = name
        self.is_stored_computed = stored_computed
        self.recursive = recursive


class TestKnownSubtractionSemantics(unittest.TestCase):
    """(ids - marked) - to_recompute must equal ids - (marked | to_recompute)."""

    def test_marked_and_accumulated_with_ordered_sets(self) -> None:
        engine = ComputeEngine(pending_factory=OrderedSet)
        field = _MockField("parent_total", stored_computed=True, recursive=True)
        engine.schedule(field, [10, 11])  # pre-existing pending (marked)

        scheduler = RecomputeScheduler(
            engine,
            marked=engine.pending,
            schedule_inline=True,
            set_factory=OrderedSet,
        )
        scheduler.process_entry(field, OrderedSet([20, 21]))  # accumulates
        recursive_ids = scheduler.process_entry(
            field, OrderedSet([10, 20, 30, 11, 21, 31])
        )

        # 10/11 in marked, 20/21 accumulated -> only 30/31 survive
        self.assertEqual(recursive_ids, frozenset({30, 31}))
        self.assertEqual(list(engine.pending_ids(field)), [10, 11, 20, 21, 30, 31])

    def test_only_marked(self) -> None:
        engine = ComputeEngine()
        field = _MockField("f", stored_computed=True, recursive=True)
        scheduler = RecomputeScheduler(engine, marked={field: {1, 2}})
        self.assertEqual(scheduler.process_entry(field, {1, 2, 3}), frozenset({3}))

    def test_only_accumulated(self) -> None:
        engine = ComputeEngine()
        field = _MockField("f", stored_computed=True, recursive=True)
        scheduler = RecomputeScheduler(engine)
        scheduler.process_entry(field, {1, 2})
        self.assertEqual(scheduler.process_entry(field, {2, 3}), frozenset({3}))

    def test_neither_leaves_ids_untouched(self) -> None:
        engine = ComputeEngine()
        field = _MockField("f", stored_computed=True, recursive=True)
        scheduler = RecomputeScheduler(engine)
        self.assertEqual(scheduler.process_entry(field, {1, 2}), frozenset({1, 2}))

    def test_fully_known_is_a_noop(self) -> None:
        engine = ComputeEngine()
        field = _MockField("f", stored_computed=True, recursive=True)
        scheduler = RecomputeScheduler(engine, marked={field: {1}})
        scheduler.process_entry(field, {2})
        self.assertEqual(scheduler.process_entry(field, {1, 2}), frozenset())
        self.assertEqual(scheduler.to_recompute[field], {2})


class _MembershipOnlyView:
    """A cached-ids stand-in that forbids iteration.

    The pre-fix ``ids & cached_ids`` (``abc.Set.__and__``) iterated the whole
    cached-id view — O(|cache|) per entry, in cache order. The fixed branch
    may only membership-test it while iterating the entry's own ids.
    """

    def __init__(self, keys) -> None:
        self._keys = set(keys)
        self.lookups: list = []

    def __contains__(self, item) -> bool:
        self.lookups.append(item)
        return item in self._keys

    def __iter__(self):
        raise AssertionError("cached_ids must never be iterated (O(|cache|))")

    def __len__(self) -> int:
        return len(self._keys)


class TestCachedIdsIntersection(unittest.TestCase):
    """The non-stored branch intersects by iterating the entry's ids."""

    def test_iterates_entry_ids_not_cache(self) -> None:
        """The intersection walks the entry's ids in recordset order and only
        membership-tests the cached-id view (never iterates it)."""
        engine = ComputeEngine(pending_factory=OrderedSet)
        field = _MockField("display", stored_computed=False, recursive=True)
        scheduler = RecomputeScheduler(
            engine, marked=engine.pending, set_factory=OrderedSet
        )

        cached = _MembershipOnlyView([9, 3, 7, 1])
        recursive_ids = scheduler.process_entry(
            field, OrderedSet([1, 3, 5, 7]), cached_ids=cached
        )

        # membership tests happened in the entry's (recordset) order
        self.assertEqual(cached.lookups, [1, 3, 5, 7])
        self.assertEqual(recursive_ids, frozenset({1, 3, 7}))
        self.assertEqual(scheduler.to_invalidate, [(field, frozenset({1, 3, 7}))])

    def test_intersection_semantics_with_plain_sets(self) -> None:
        engine = ComputeEngine()
        field = _MockField("display", stored_computed=False, recursive=True)
        scheduler = RecomputeScheduler(engine)
        recursive_ids = scheduler.process_entry(
            field, {1, 2, 3, 4, 5}, cached_ids={2, 4, 99}
        )
        self.assertEqual(recursive_ids, frozenset({2, 4}))

    def test_seen_then_cached_filter_composition(self) -> None:
        engine = ComputeEngine()
        field = _MockField("display", stored_computed=False, recursive=True)
        scheduler = RecomputeScheduler(engine)
        scheduler.process_entry(field, {1, 2}, cached_ids={1, 2})
        # 1 seen, 4 not cached -> only 3
        recursive_ids = scheduler.process_entry(field, {1, 3, 4}, cached_ids={1, 3})
        self.assertEqual(recursive_ids, frozenset({3}))


if __name__ == "__main__":
    unittest.main()
