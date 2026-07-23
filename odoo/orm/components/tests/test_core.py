"""Tests for the OrmCore Layer 1 facade.

These tests verify that OrmCore faithfully delegates to FieldCache and
ComputeEngine under the *same* method names, producing identical results to
calling the underlying components directly. Operations not exposed on the facade
(``set_value``, ``invalidate_*``, ``clear`` …) are reached via ``core.cache`` /
``core.engine`` and covered by ``test_cache.py`` / ``test_compute.py``.
"""

import unittest
from collections import namedtuple
from unittest.mock import Mock

from odoo.orm.components.cache import FieldCache
from odoo.orm.components.compute import ComputeEngine
from odoo.orm.components.core import OrmCore

# Drift guard (ADR-0010 step 3): each OrmCore pass-through and the
# FieldCache/ComputeEngine method it MUST delegate to, with the call arity.
# ``clear_cache`` is the one intentional rename (-> cache.clear); ``new_scheduler``
# is a factory, not a pass-through, and is covered by its own tests above.
# (orm_method, target, underlying_method, arity, returns_value)
# ``returns_value`` is False for the void pass-throughs (the facade calls but
# does not return the result) — for those only the delegation is checked.
_DELEGATIONS = [
    ("get_field_data", "cache", "get_field_data", 1, True),
    ("get_field_data_or_none", "cache", "get_field_data_or_none", 1, True),
    ("mark_dirty", "cache", "mark_dirty", 2, False),
    ("get_dirty", "cache", "get_dirty", 1, True),
    ("pop_dirty", "cache", "pop_dirty", 1, True),
    ("pop_dirty_for_model", "cache", "pop_dirty_for_model", 1, True),
    ("has_dirty_field", "cache", "has_dirty_field", 1, True),
    ("is_any_dirty", "cache", "is_any_dirty", 0, True),
    ("add_patch", "cache", "add_patch", 3, False),
    ("get_patches", "cache", "get_patches", 1, True),
    ("iter_field_items", "cache", "iter_field_items", 0, True),
    ("clear_cache", "cache", "clear", 0, False),
    ("schedule", "engine", "schedule", 2, False),
    ("mark_done", "engine", "mark_done", 2, False),
    ("is_pending", "engine", "is_pending", 2, True),
    ("has_pending_field", "engine", "has_pending_field", 1, True),
    ("has_pending", "engine", "has_pending", 0, True),
    ("pending_ids", "engine", "pending_ids", 1, True),
    ("pending_fields", "engine", "pending_fields", 0, True),
    ("discard_field", "engine", "discard_field", 1, False),
    ("is_protected", "engine", "is_protected", 2, True),
    ("protected_ids", "engine", "protected_ids", 1, True),
    ("push_protection", "engine", "push_protection", 0, False),
    ("pop_protection", "engine", "pop_protection", 0, True),
    ("protect", "engine", "protect", 2, False),
]
_NON_PASSTHROUGH = {"new_scheduler"}  # factory, not a same-name delegation

# Lightweight field stub — hashable, named for debugging.
FakeField = namedtuple("FakeField", ["model_name", "name"])


class TestOrmCoreCache(unittest.TestCase):
    """Test cache operations through OrmCore."""

    def setUp(self) -> None:
        self.core = OrmCore()
        self.f1 = FakeField("res.partner", "name")
        self.f2 = FakeField("res.partner", "email")

    def test_get_field_data_returns_live_dict(self) -> None:
        self.core.cache.set_value(self.f1, 1, "Alice")
        data = self.core.get_field_data(self.f1)
        self.assertEqual(data[1], "Alice")
        # mutations on the returned dict are visible through the cache
        data[2] = "Bob"
        self.assertEqual(self.core.cache.get_value(self.f1, 2), "Bob")

    def test_get_field_data_or_none(self) -> None:
        self.assertIsNone(self.core.get_field_data_or_none(self.f1))
        self.core.cache.set_value(self.f1, 1, "X")
        self.assertIsNotNone(self.core.get_field_data_or_none(self.f1))

    # -- dirty tracking --

    def test_mark_dirty_and_pop(self) -> None:
        self.core.mark_dirty(self.f1, [1, 2])
        self.assertTrue(self.core.has_dirty_field(self.f1))
        self.assertTrue(self.core.is_any_dirty())
        dirty = self.core.pop_dirty(self.f1)
        self.assertEqual(dirty, {1, 2})
        self.assertFalse(self.core.has_dirty_field(self.f1))

    def test_get_dirty(self) -> None:
        self.core.mark_dirty(self.f1, [1, 2])
        dirty = self.core.get_dirty(self.f1)
        self.assertEqual(dirty, {1, 2})
        # get_dirty does NOT remove — still dirty
        self.assertTrue(self.core.has_dirty_field(self.f1))

    def test_get_dirty_none(self) -> None:
        self.assertIsNone(self.core.get_dirty(self.f1))

    def test_pop_dirty_empty(self) -> None:
        self.assertIsNone(self.core.pop_dirty(self.f1))

    # -- patches --

    def test_add_and_get_patches(self) -> None:
        self.core.add_patch(self.f1, 1, 100)
        self.core.add_patch(self.f1, 1, 101)
        patches = self.core.get_patches(self.f1)
        self.assertEqual(patches[1], [100, 101])

    def test_get_patches_none(self) -> None:
        self.assertIsNone(self.core.get_patches(self.f1))

    # -- iteration --

    def test_iter_field_items(self) -> None:
        self.core.cache.set_value(self.f1, 1, "a")
        items = dict(self.core.iter_field_items())
        self.assertIn(self.f1, items)
        self.assertEqual(items[self.f1][1], "a")


class TestOrmCoreCompute(unittest.TestCase):
    """Test compute operations through OrmCore."""

    def setUp(self) -> None:
        self.core = OrmCore()
        self.f1 = FakeField("sale.order", "amount")
        self.f2 = FakeField("sale.order", "tax")

    def test_schedule_and_pending(self) -> None:
        self.core.schedule(self.f1, [1, 2])
        self.assertTrue(self.core.has_pending_field(self.f1))
        self.assertTrue(self.core.has_pending())
        self.assertEqual(self.core.pending_ids(self.f1), {1, 2})

    def test_is_pending(self) -> None:
        self.core.schedule(self.f1, [1, 2])
        self.assertTrue(self.core.is_pending(self.f1, 1))
        self.assertFalse(self.core.is_pending(self.f1, 3))

    def test_is_pending_no_schedule(self) -> None:
        self.assertFalse(self.core.is_pending(self.f1, 1))

    def test_has_pending_false(self) -> None:
        self.assertFalse(self.core.has_pending_field(self.f1))
        self.assertFalse(self.core.has_pending())

    def test_pending_ids_empty(self) -> None:
        self.assertEqual(self.core.pending_ids(self.f1), ())

    def test_mark_done(self) -> None:
        self.core.schedule(self.f1, [1, 2, 3])
        self.core.mark_done(self.f1, [1, 2])
        self.assertEqual(self.core.pending_ids(self.f1), {3})

    def test_mark_done_clears_entry(self) -> None:
        self.core.schedule(self.f1, [1])
        self.core.mark_done(self.f1, [1])
        self.assertFalse(self.core.has_pending_field(self.f1))

    def test_pending_fields(self) -> None:
        self.core.schedule(self.f1, [1])
        self.core.schedule(self.f2, [2])
        self.assertEqual(set(self.core.pending_fields()), {self.f1, self.f2})

    def test_discard_field(self) -> None:
        self.core.schedule(self.f1, [1, 2])
        self.core.discard_field(self.f1)
        self.assertFalse(self.core.has_pending_field(self.f1))

    def test_discard_field_noop(self) -> None:
        # should not raise
        self.core.discard_field(self.f1)

    # -- protection --

    def test_protection_lifecycle(self) -> None:
        self.core.push_protection()
        self.core.protect(self.f1, frozenset([1, 2]))
        self.assertTrue(self.core.is_protected(self.f1, 1))
        self.assertFalse(self.core.is_protected(self.f1, 3))
        self.assertEqual(self.core.protected_ids(self.f1), frozenset([1, 2]))
        self.core.pop_protection()
        self.assertFalse(self.core.is_protected(self.f1, 1))

    def test_protection_stacking(self) -> None:
        self.core.push_protection()
        self.core.protect(self.f1, frozenset([1]))
        self.core.push_protection()
        self.core.protect(self.f1, frozenset([2]))
        self.assertTrue(self.core.is_protected(self.f1, 1))
        self.assertTrue(self.core.is_protected(self.f1, 2))
        self.core.pop_protection()
        self.assertTrue(self.core.is_protected(self.f1, 1))
        self.assertFalse(self.core.is_protected(self.f1, 2))

    # -- scheduler factory --

    def test_new_scheduler_is_bound_to_engine(self) -> None:
        from odoo.orm.components.recompute import RecomputeScheduler

        sched = self.core.new_scheduler()
        self.assertIsInstance(sched, RecomputeScheduler)
        self.assertIs(sched._engine, self.core.engine)
        # each call returns a fresh, independent scheduler
        self.assertIsNot(sched, self.core.new_scheduler())

    def test_new_scheduler_seeds_marked_from_live_pending_in_both_modes(self) -> None:
        """Both scheduler modes prune against the engine's LIVE pending map.

        Ids already pending from earlier modified() calls in the transaction
        must never be re-traversed, whether the scheduler batches (default) or
        schedules inline — the seed is the live map itself, not a snapshot.
        """
        self.core.schedule(self.f1, [1, 2])
        batch = self.core.new_scheduler()
        inline = self.core.new_scheduler(inline=True)
        for sched in (batch, inline):
            self.assertIs(sched._marked, self.core.engine.pending)
            self.assertEqual(sched._marked.get(self.f1), {1, 2})
        # live, not a copy: later scheduling is visible to existing schedulers
        self.core.schedule(self.f2, [3])
        self.assertEqual(batch._marked.get(self.f2), {3})

    def test_new_scheduler_inline_flag(self) -> None:
        # Only the inline scheduler pushes entries into the engine's pending.
        self.assertFalse(self.core.new_scheduler()._inline)
        self.assertTrue(self.core.new_scheduler(inline=True)._inline)

    def test_new_scheduler_propagates_engine_set_factory(self) -> None:
        """to_recompute uses the engine's pending-set factory (determinism)."""

        class TrackingSet(set):
            pass

        core = OrmCore(engine=ComputeEngine(pending_factory=TrackingSet))
        sched = core.new_scheduler()
        self.assertIsInstance(sched.to_recompute["field"], TrackingSet)


class TestOrmCoreLifecycle(unittest.TestCase):
    """Test the clear_cache lifecycle operation."""

    def setUp(self) -> None:
        self.core = OrmCore()
        self.f1 = FakeField("x", "a")

    def test_clear_cache_only(self) -> None:
        self.core.cache.set_value(self.f1, 1, "v")
        self.core.schedule(self.f1, [1])
        self.core.clear_cache()
        # cache data is gone, but compute state survives
        self.assertIsNone(self.core.cache.get_value(self.f1, 1, None))
        self.assertTrue(self.core.has_pending_field(self.f1))


class TestOrmCoreConstructor(unittest.TestCase):
    """Test constructor variants."""

    def test_default_creates_components(self) -> None:
        core = OrmCore()
        self.assertIsInstance(core.cache, FieldCache)
        self.assertIsInstance(core.engine, ComputeEngine)

    def test_custom_components(self) -> None:
        from odoo.tools import OrderedSet

        cache = FieldCache(dirty_factory=OrderedSet)
        engine = ComputeEngine(pending_factory=OrderedSet)
        core = OrmCore(cache=cache, engine=engine)
        self.assertIs(core.cache, cache)
        self.assertIs(core.engine, engine)

    def test_repr(self) -> None:
        core = OrmCore()
        r = repr(core)
        self.assertIn("OrmCore", r)
        self.assertIn("FieldCache", r)
        self.assertIn("ComputeEngine", r)


class TestOrmCoreDelegationConsistency(unittest.TestCase):
    """Verify that OrmCore methods produce identical results to direct
    component access — the facade must be a faithful, transparent pass-through.
    """

    def setUp(self) -> None:
        self.cache = FieldCache()
        self.engine = ComputeEngine()
        self.core = OrmCore(cache=self.cache, engine=self.engine)
        self.f1 = FakeField("m", "f")

    def test_get_field_data_is_same_object(self) -> None:
        self.cache.set_value(self.f1, 1, "v")
        self.assertIs(
            self.core.get_field_data(self.f1),
            self.cache.get_field_data(self.f1),
        )

    def test_pending_ids_same_object(self) -> None:
        self.core.schedule(self.f1, [1, 2])
        self.assertIs(
            self.core.pending_ids(self.f1),
            self.engine.pending_ids(self.f1),
        )

    def test_has_pending_field_matches_engine(self) -> None:
        self.assertEqual(
            self.core.has_pending_field(self.f1),
            self.engine.has_pending_field(self.f1),
        )
        self.core.schedule(self.f1, [1])
        self.assertEqual(
            self.core.has_pending_field(self.f1),
            self.engine.has_pending_field(self.f1),
        )

    def test_has_pending_matches_engine(self) -> None:
        # facade.has_pending() is the no-arg "any pending" predicate, faithful
        # to ComputeEngine.has_pending().
        self.assertEqual(self.core.has_pending(), self.engine.has_pending())
        self.core.schedule(self.f1, [1])
        self.assertEqual(self.core.has_pending(), self.engine.has_pending())

    def test_is_pending_matches_engine(self) -> None:
        self.core.schedule(self.f1, [1])
        self.assertEqual(
            self.core.is_pending(self.f1, 1),
            self.engine.is_pending(self.f1, 1),
        )
        self.assertEqual(
            self.core.is_pending(self.f1, 999),
            self.engine.is_pending(self.f1, 999),
        )

    def test_get_dirty_matches_cache(self) -> None:
        self.assertIs(
            self.core.get_dirty(self.f1),
            self.cache.get_dirty(self.f1),
        )
        self.core.mark_dirty(self.f1, [1])
        self.assertIs(
            self.core.get_dirty(self.f1),
            self.cache.get_dirty(self.f1),
        )

    def test_dirty_matches_cache(self) -> None:
        self.core.mark_dirty(self.f1, [1])
        self.assertEqual(
            self.core.has_dirty_field(self.f1),
            self.cache.has_dirty_field(self.f1),
        )

    def test_protection_matches_engine(self) -> None:
        self.core.push_protection()
        self.core.protect(self.f1, frozenset([1]))
        self.assertEqual(
            self.core.is_protected(self.f1, 1),
            self.engine.is_protected(self.f1, 1),
        )
        self.assertEqual(
            self.core.protected_ids(self.f1),
            self.engine.protected_ids(self.f1),
        )


class TestOrmCoreDelegationDrift(unittest.TestCase):
    """Drift guard (ADR-0010): every OrmCore pass-through delegates to the
    same-named FieldCache / ComputeEngine method.

    Uses ``Mock(spec=...)``, which raises ``AttributeError`` if OrmCore calls a
    method the underlying class no longer has — so an upstream rename/removal
    fails *here*, loudly, instead of silently breaking ``env._core``.
    """

    def test_pass_throughs_delegate_by_same_name(self) -> None:
        for orm_method, target, underlying, arity, returns in _DELEGATIONS:
            with self.subTest(method=orm_method):
                cache = Mock(spec=FieldCache)
                engine = Mock(spec=ComputeEngine)
                core = OrmCore(cache=cache, engine=engine)
                target_obj = cache if target == "cache" else engine
                args = tuple(object() for _ in range(arity))

                result = getattr(core, orm_method)(*args)

                underlying_mock = getattr(target_obj, underlying)
                underlying_mock.assert_called_once_with(*args)
                if returns:
                    self.assertIs(result, underlying_mock.return_value)

    def test_table_covers_every_pass_through(self) -> None:
        """Guard the guard: a new public OrmCore method must be added to
        ``_DELEGATIONS`` (or to ``_NON_PASSTHROUGH``), or this fails."""
        documented = {row[0] for row in _DELEGATIONS}
        public = {
            name
            for name in vars(OrmCore)
            if not name.startswith("_") and callable(getattr(OrmCore, name))
        }
        self.assertEqual(public - _NON_PASSTHROUGH, documented)


if __name__ == "__main__":
    unittest.main()
