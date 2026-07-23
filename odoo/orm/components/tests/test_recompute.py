"""Pure-Python tests for RecomputeScheduler — no Odoo, no database required.

Uses lightweight mock fields (simple objects with ``recursive`` and
``is_stored_computed`` attributes) to prove the scheduler is fully
decoupled from the ORM runtime.
"""

import unittest

from odoo.orm.components.compute import ComputeEngine
from odoo.orm.components.recompute import RecomputeScheduler


class _MockField:
    """Lightweight field stub for testing the scheduler."""

    __slots__ = ("is_stored_computed", "name", "recursive")

    def __init__(
        self, name: str, *, stored_computed: bool = False, recursive: bool = False
    ) -> None:
        self.name = name
        self.is_stored_computed = stored_computed
        self.recursive = recursive

    def __repr__(self) -> str:
        return f"<MockField {self.name}>"

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _MockField) and self.name == other.name


class TestProtection(unittest.TestCase):
    """Protection subtraction: protected IDs are excluded from results."""

    def test_all_protected(self) -> None:
        engine = ComputeEngine()
        engine.push_protection()
        field = _MockField("total", stored_computed=True)
        engine.protect(field, frozenset({1, 2, 3}))

        scheduler = RecomputeScheduler(engine)
        result = scheduler.process_entry(field, {1, 2, 3})

        self.assertEqual(result, frozenset())
        self.assertEqual(dict(scheduler.to_recompute), {})

    def test_partial_protection(self) -> None:
        engine = ComputeEngine()
        engine.push_protection()
        field = _MockField("total", stored_computed=True)
        engine.protect(field, frozenset({2}))

        scheduler = RecomputeScheduler(engine)
        scheduler.process_entry(field, {1, 2, 3})

        self.assertEqual(scheduler.to_recompute[field], {1, 3})

    def test_no_protection(self) -> None:
        engine = ComputeEngine()
        field = _MockField("total", stored_computed=True)

        scheduler = RecomputeScheduler(engine)
        scheduler.process_entry(field, {1, 2, 3})

        self.assertEqual(scheduler.to_recompute[field], {1, 2, 3})

    def test_protection_on_different_field(self) -> None:
        engine = ComputeEngine()
        engine.push_protection()
        field_a = _MockField("a", stored_computed=True)
        field_b = _MockField("b", stored_computed=True)
        engine.protect(field_a, frozenset({1, 2}))

        scheduler = RecomputeScheduler(engine)
        scheduler.process_entry(field_b, {1, 2, 3})

        self.assertEqual(scheduler.to_recompute[field_b], {1, 2, 3})


class TestRouting(unittest.TestCase):
    """Stored-computed → to_recompute, non-stored → to_invalidate."""

    def test_stored_computed_goes_to_recompute(self) -> None:
        engine = ComputeEngine()
        field = _MockField("total", stored_computed=True)

        scheduler = RecomputeScheduler(engine)
        scheduler.process_entry(field, {1, 2})

        self.assertIn(field, scheduler.to_recompute)
        self.assertEqual(scheduler.to_recompute[field], {1, 2})
        self.assertEqual(scheduler.to_invalidate, [])

    def test_non_stored_goes_to_invalidate(self) -> None:
        engine = ComputeEngine()
        field = _MockField("display_name", stored_computed=False)

        scheduler = RecomputeScheduler(engine)
        scheduler.process_entry(field, {1, 2})

        self.assertEqual(dict(scheduler.to_recompute), {})
        self.assertEqual(len(scheduler.to_invalidate), 1)
        self.assertEqual(scheduler.to_invalidate[0][0], field)
        self.assertEqual(scheduler.to_invalidate[0][1], frozenset({1, 2}))

    def test_multiple_entries_accumulate(self) -> None:
        engine = ComputeEngine()
        field = _MockField("total", stored_computed=True)

        scheduler = RecomputeScheduler(engine)
        scheduler.process_entry(field, {1, 2})
        scheduler.process_entry(field, {3, 4})

        self.assertEqual(scheduler.to_recompute[field], {1, 2, 3, 4})

    def test_multiple_fields(self) -> None:
        engine = ComputeEngine()
        field_a = _MockField("a", stored_computed=True)
        field_b = _MockField("b", stored_computed=False)

        scheduler = RecomputeScheduler(engine)
        scheduler.process_entry(field_a, {1})
        scheduler.process_entry(field_b, {2})

        self.assertEqual(scheduler.to_recompute[field_a], {1})
        self.assertEqual(scheduler.to_invalidate[0], (field_b, frozenset({2})))


class TestRecursiveStoredComputed(unittest.TestCase):
    """Recursive stored-computed fields: cycle detection via marked + to_recompute."""

    def test_recursive_returns_ids_for_traversal(self) -> None:
        engine = ComputeEngine()
        field = _MockField("parent_total", stored_computed=True, recursive=True)

        scheduler = RecomputeScheduler(engine)
        recursive_ids = scheduler.process_entry(field, {1, 2, 3})

        self.assertEqual(recursive_ids, frozenset({1, 2, 3}))
        self.assertEqual(scheduler.to_recompute[field], {1, 2, 3})

    def test_non_recursive_returns_empty(self) -> None:
        engine = ComputeEngine()
        field = _MockField("total", stored_computed=True, recursive=False)

        scheduler = RecomputeScheduler(engine)
        recursive_ids = scheduler.process_entry(field, {1, 2, 3})

        self.assertEqual(recursive_ids, frozenset())

    def test_cycle_detection_via_marked(self) -> None:
        """IDs already in `marked` (engine.pending) are skipped."""
        engine = ComputeEngine()
        field = _MockField("parent_total", stored_computed=True, recursive=True)
        # Simulate IDs already pending from a previous call
        marked = {field: {1, 2}}

        scheduler = RecomputeScheduler(engine, marked=marked)
        recursive_ids = scheduler.process_entry(field, {1, 2, 3})

        # Only ID 3 is new
        self.assertEqual(recursive_ids, frozenset({3}))
        self.assertEqual(scheduler.to_recompute[field], {3})

    def test_cycle_detection_via_accumulation(self) -> None:
        """IDs accumulated in to_recompute from earlier entries are skipped."""
        engine = ComputeEngine()
        field = _MockField("parent_total", stored_computed=True, recursive=True)

        scheduler = RecomputeScheduler(engine)
        # First entry marks {1, 2}
        scheduler.process_entry(field, {1, 2})
        # Second entry tries {2, 3} — ID 2 should be skipped
        recursive_ids = scheduler.process_entry(field, {2, 3})

        self.assertEqual(recursive_ids, frozenset({3}))
        self.assertEqual(scheduler.to_recompute[field], {1, 2, 3})

    def test_cycle_detection_marked_plus_accumulated(self) -> None:
        """Both marked (external) and accumulated (internal) IDs are excluded."""
        engine = ComputeEngine()
        field = _MockField("parent_total", stored_computed=True, recursive=True)
        marked = {field: {1}}

        scheduler = RecomputeScheduler(engine, marked=marked)
        scheduler.process_entry(field, {2})  # marks {2}
        recursive_ids = scheduler.process_entry(field, {1, 2, 3})

        # 1 is in marked, 2 is in to_recompute → only 3
        self.assertEqual(recursive_ids, frozenset({3}))

    def test_all_known_returns_empty(self) -> None:
        engine = ComputeEngine()
        field = _MockField("parent_total", stored_computed=True, recursive=True)
        marked = {field: {1, 2, 3}}

        scheduler = RecomputeScheduler(engine, marked=marked)
        recursive_ids = scheduler.process_entry(field, {1, 2, 3})

        self.assertEqual(recursive_ids, frozenset())
        # Nothing added to to_recompute
        self.assertNotIn(field, scheduler.to_recompute)


class TestRecursiveNonStored(unittest.TestCase):
    """Recursive non-stored fields: filter to cached IDs only."""

    def test_filter_to_cached_ids(self) -> None:
        engine = ComputeEngine()
        field = _MockField("display", stored_computed=False, recursive=True)

        scheduler = RecomputeScheduler(engine)
        recursive_ids = scheduler.process_entry(
            field,
            {1, 2, 3, 4, 5},
            cached_ids={2, 4},
        )

        # Only IDs 2 and 4 are in cache
        self.assertEqual(recursive_ids, frozenset({2, 4}))
        self.assertEqual(len(scheduler.to_invalidate), 1)
        self.assertEqual(scheduler.to_invalidate[0][1], frozenset({2, 4}))

    def test_no_cached_ids_skips(self) -> None:
        engine = ComputeEngine()
        field = _MockField("display", stored_computed=False, recursive=True)

        scheduler = RecomputeScheduler(engine)
        recursive_ids = scheduler.process_entry(
            field,
            {1, 2, 3},
            cached_ids=set(),
        )

        self.assertEqual(recursive_ids, frozenset())
        self.assertEqual(scheduler.to_invalidate, [])

    def test_cached_ids_none_means_no_filter(self) -> None:
        """When cached_ids is None, all IDs are processed (no filter)."""
        engine = ComputeEngine()
        field = _MockField("display", stored_computed=False, recursive=True)

        scheduler = RecomputeScheduler(engine)
        recursive_ids = scheduler.process_entry(
            field,
            {1, 2, 3},
            cached_ids=None,
        )

        self.assertEqual(recursive_ids, frozenset({1, 2, 3}))

    def test_cycle_detection_non_stored(self) -> None:
        """Non-stored recursive: IDs processed in earlier entries are skipped.

        This prevents infinite loops in cyclic hierarchies (e.g. A parent of B,
        B parent of A) where deferred invalidation can't break the cycle.
        """
        engine = ComputeEngine()
        field = _MockField("display", stored_computed=False, recursive=True)

        scheduler = RecomputeScheduler(engine)
        # First round: process {1, 2}
        r1 = scheduler.process_entry(field, {1, 2}, cached_ids={1, 2, 3})
        self.assertEqual(r1, frozenset({1, 2}))

        # Second round (simulating recursive traversal returning same IDs):
        # {1, 2} already seen → only {3} is new
        r2 = scheduler.process_entry(field, {1, 2, 3}, cached_ids={1, 2, 3})
        self.assertEqual(r2, frozenset({3}))

        # Third round: all IDs already seen → empty
        r3 = scheduler.process_entry(field, {1, 2, 3}, cached_ids={1, 2, 3})
        self.assertEqual(r3, frozenset())

    def test_cycle_detection_non_stored_interacts_with_cached(self) -> None:
        """Cycle detection is applied BEFORE cached_ids filter."""
        engine = ComputeEngine()
        field = _MockField("display", stored_computed=False, recursive=True)

        scheduler = RecomputeScheduler(engine)
        # First: process {1, 2} (both cached)
        scheduler.process_entry(field, {1, 2}, cached_ids={1, 2})

        # Second: {1, 3, 4}, cached={1, 3}
        # 1 already seen → removed. {3, 4} remain. cached={1,3} → {3}
        r2 = scheduler.process_entry(field, {1, 3, 4}, cached_ids={1, 3})
        self.assertEqual(r2, frozenset({3}))


class TestProtectionWithRecursive(unittest.TestCase):
    """Protection subtraction applies BEFORE cycle detection."""

    def test_protected_subtracted_before_cycle_check(self) -> None:
        engine = ComputeEngine()
        engine.push_protection()
        field = _MockField("parent_total", stored_computed=True, recursive=True)
        engine.protect(field, frozenset({2}))

        scheduler = RecomputeScheduler(engine)
        recursive_ids = scheduler.process_entry(field, {1, 2, 3})

        # ID 2 is protected → removed before cycle detection
        self.assertEqual(recursive_ids, frozenset({1, 3}))
        self.assertEqual(scheduler.to_recompute[field], {1, 3})

    def test_protection_plus_cached_filter(self) -> None:
        engine = ComputeEngine()
        engine.push_protection()
        field = _MockField("display", stored_computed=False, recursive=True)
        engine.protect(field, frozenset({1}))

        scheduler = RecomputeScheduler(engine)
        recursive_ids = scheduler.process_entry(
            field,
            {1, 2, 3, 4},
            cached_ids={2, 3},
        )

        # 1 is protected, then filter to cached {2, 3}
        self.assertEqual(recursive_ids, frozenset({2, 3}))


class _SpyEngine(ComputeEngine):
    """ComputeEngine recording every ``schedule`` call (field, ids-as-given)."""

    def __init__(self) -> None:
        super().__init__()
        self.schedule_calls: list[tuple] = []

    def schedule(self, field, ids) -> None:
        ids = list(ids)
        self.schedule_calls.append((field, list(ids)))
        super().schedule(field, ids)


class TestInlineScheduling(unittest.TestCase):
    """schedule_inline=True pushes per-entry deltas into the engine's pending."""

    def test_batch_mode_never_touches_engine_pending(self) -> None:
        engine = _SpyEngine()
        field = _MockField("total", stored_computed=True)

        scheduler = RecomputeScheduler(engine)
        scheduler.process_entry(field, {1, 2})

        self.assertEqual(engine.schedule_calls, [])
        self.assertFalse(engine.has_pending_field(field))

    def test_inline_schedules_each_entry(self) -> None:
        engine = _SpyEngine()
        field = _MockField("total", stored_computed=True)

        scheduler = RecomputeScheduler(engine, schedule_inline=True)
        scheduler.process_entry(field, {1, 2})
        scheduler.process_entry(field, {3})

        self.assertEqual(engine.pending_ids(field), {1, 2, 3})
        self.assertEqual(scheduler.to_recompute[field], {1, 2, 3})

    def test_inline_schedules_delta_not_cumulative(self) -> None:
        """Each entry schedules only its own ids, never the accumulated set.

        Regression guard for the O(k*n) re-scheduling of the full
        ``to_recompute[field]`` set per entry, which also re-pended ids that a
        mid-traversal inline compute had already drained.
        """
        engine = _SpyEngine()
        field = _MockField("total", stored_computed=True)

        scheduler = RecomputeScheduler(engine, schedule_inline=True)
        scheduler.process_entry(field, {1, 2})
        # a mid-traversal inline compute drains the first batch
        engine.mark_done(field, [1, 2])
        scheduler.process_entry(field, {3, 4})

        self.assertEqual(
            [set(ids) for _f, ids in engine.schedule_calls],
            [{1, 2}, {3, 4}],
        )
        # drained ids are NOT re-pended by the later, unrelated entry
        self.assertEqual(engine.pending_ids(field), {3, 4})

    def test_inline_skips_protected_and_invalidate_entries(self) -> None:
        engine = _SpyEngine()
        engine.push_protection()
        stored = _MockField("total", stored_computed=True)
        non_stored = _MockField("display", stored_computed=False)
        engine.protect(stored, frozenset({1}))

        scheduler = RecomputeScheduler(engine, schedule_inline=True)
        scheduler.process_entry(stored, {1, 2})
        scheduler.process_entry(non_stored, {5})

        # only the unprotected stored id reaches the engine
        self.assertEqual(engine.pending_ids(stored), {2})
        self.assertFalse(engine.has_pending_field(non_stored))

    def test_live_pending_seed_prevents_retraversal(self) -> None:
        """Ids already pending in the engine (from an earlier modified() call)
        are neither re-traversed nor re-accumulated when ``marked`` is the
        engine's live pending map — a second traversal only expands new ids.
        """
        engine = _SpyEngine()
        field = _MockField("parent_total", stored_computed=True, recursive=True)
        # earlier modified() call left ids pending
        engine.schedule(field, [1, 2])
        engine.schedule_calls.clear()

        scheduler = RecomputeScheduler(
            engine, marked=engine.pending, schedule_inline=True
        )
        recursive_ids = scheduler.process_entry(field, {1, 2, 3})

        # only the genuinely new id is traversed further and scheduled
        self.assertEqual(recursive_ids, frozenset({3}))
        self.assertEqual(scheduler.to_recompute[field], {3})
        self.assertEqual(engine.schedule_calls, [(field, [3])])
        self.assertEqual(engine.pending_ids(field), {1, 2, 3})

        # a fully-known second traversal is a complete no-op
        engine.schedule_calls.clear()
        recursive_ids = scheduler.process_entry(field, {1, 2, 3})
        self.assertEqual(recursive_ids, frozenset())
        self.assertEqual(engine.schedule_calls, [])


class TestDeterministicOrder(unittest.TestCase):
    """Ids flow into the engine's pending map in insertion order when both
    the scheduler and the engine use an order-preserving set factory."""

    def test_insertion_order_preserved_end_to_end(self) -> None:
        from odoo.tools import OrderedSet

        engine = ComputeEngine(pending_factory=OrderedSet)
        field = _MockField("total", stored_computed=True)
        scheduler = RecomputeScheduler(
            engine, schedule_inline=True, set_factory=OrderedSet
        )

        scheduler.process_entry(field, OrderedSet([7, 3, 9]))
        scheduler.process_entry(field, OrderedSet([1, 8]))

        self.assertEqual(list(scheduler.to_recompute[field]), [7, 3, 9, 1, 8])
        self.assertEqual(list(engine.pending_ids(field)), [7, 3, 9, 1, 8])

    def test_order_survives_protection_subtraction(self) -> None:
        from odoo.tools import OrderedSet

        engine = ComputeEngine(pending_factory=OrderedSet)
        engine.push_protection()
        field = _MockField("total", stored_computed=True)
        engine.protect(field, frozenset({3}))
        scheduler = RecomputeScheduler(
            engine, schedule_inline=True, set_factory=OrderedSet
        )

        scheduler.process_entry(field, OrderedSet([7, 3, 9, 1]))

        self.assertEqual(list(engine.pending_ids(field)), [7, 9, 1])

    def test_default_factory_is_plain_set(self) -> None:
        engine = ComputeEngine()
        scheduler = RecomputeScheduler(engine)
        self.assertIs(type(scheduler.to_recompute["x"]), set)


class TestRepr(unittest.TestCase):
    """Repr includes summary counts."""

    def test_repr_empty(self) -> None:
        engine = ComputeEngine()
        scheduler = RecomputeScheduler(engine)
        self.assertIn("recompute=0f/0e", repr(scheduler))
        self.assertIn("invalidate=0f/0e", repr(scheduler))

    def test_repr_with_data(self) -> None:
        engine = ComputeEngine()
        field_a = _MockField("a", stored_computed=True)
        field_b = _MockField("b", stored_computed=False)

        scheduler = RecomputeScheduler(engine)
        scheduler.process_entry(field_a, {1, 2, 3})
        scheduler.process_entry(field_b, {4, 5})

        r = repr(scheduler)
        self.assertIn("recompute=1f/3e", r)
        self.assertIn("invalidate=1f/2e", r)


class TestEdgeCases(unittest.TestCase):
    """Edge cases and boundary conditions."""

    def test_empty_ids(self) -> None:
        engine = ComputeEngine()
        field = _MockField("total", stored_computed=True)

        scheduler = RecomputeScheduler(engine)
        recursive_ids = scheduler.process_entry(field, set())

        self.assertEqual(recursive_ids, frozenset())
        self.assertNotIn(field, scheduler.to_recompute)

    def test_frozenset_input(self) -> None:
        """Input IDs can be frozenset (immutable)."""
        engine = ComputeEngine()
        field = _MockField("total", stored_computed=True)

        scheduler = RecomputeScheduler(engine)
        scheduler.process_entry(field, frozenset({1, 2}))

        self.assertEqual(scheduler.to_recompute[field], {1, 2})

    def test_marked_is_live_reference(self) -> None:
        """Marked dict is a live reference — mutations are visible."""
        engine = ComputeEngine()
        field = _MockField("parent_total", stored_computed=True, recursive=True)
        marked = {field: set()}

        scheduler = RecomputeScheduler(engine, marked=marked)
        scheduler.process_entry(field, {1, 2})

        # Now mutate the live marked dict (simulating engine.pending changes)
        marked[field].add(3)
        recursive_ids = scheduler.process_entry(field, {1, 2, 3, 4})

        # 1, 2 in to_recompute, 3 in marked → only 4 is new
        self.assertEqual(recursive_ids, frozenset({4}))

    def test_interleaved_stored_and_non_stored(self) -> None:
        """Multiple entries with different field types accumulate correctly."""
        engine = ComputeEngine()
        stored = _MockField("total", stored_computed=True)
        non_stored = _MockField("display", stored_computed=False)

        scheduler = RecomputeScheduler(engine)
        scheduler.process_entry(stored, {1})
        scheduler.process_entry(non_stored, {2})
        scheduler.process_entry(stored, {3})
        scheduler.process_entry(non_stored, {4})

        self.assertEqual(scheduler.to_recompute[stored], {1, 3})
        self.assertEqual(len(scheduler.to_invalidate), 2)
        all_invalidated = {id_ for _, ids in scheduler.to_invalidate for id_ in ids}
        self.assertEqual(all_invalidated, {2, 4})


if __name__ == "__main__":
    unittest.main()
