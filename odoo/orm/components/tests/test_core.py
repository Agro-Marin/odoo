"""Tests for the OrmCore Layer 1 facade.

These tests verify that OrmCore correctly delegates to FieldCache and
ComputeEngine, and that the flat API produces identical results to
calling the underlying components directly.
"""

import unittest
from collections import namedtuple

from odoo.orm.components.cache import FieldCache
from odoo.orm.components.compute import ComputeEngine
from odoo.orm.components.core import OrmCore

# Lightweight field stub — hashable, named for debugging.
FakeField = namedtuple("FakeField", ["model_name", "name"])


class TestOrmCoreCache(unittest.TestCase):
    """Test cache operations through OrmCore."""

    def setUp(self) -> None:
        self.core = OrmCore()
        self.f1 = FakeField("res.partner", "name")
        self.f2 = FakeField("res.partner", "email")

    def test_set_and_get_value(self) -> None:
        self.core.set_value(self.f1, 1, "Alice")
        self.assertEqual(self.core.get_value(self.f1, 1), "Alice")

    def test_get_value_default(self) -> None:
        self.assertIsNone(self.core.get_value(self.f1, 999))
        self.assertEqual(self.core.get_value(self.f1, 999, "fallback"), "fallback")

    def test_field_data_returns_live_dict(self) -> None:
        self.core.set_value(self.f1, 1, "Alice")
        data = self.core.field_data(self.f1)
        self.assertEqual(data[1], "Alice")
        # mutations on the returned dict are visible
        data[2] = "Bob"
        self.assertEqual(self.core.get_value(self.f1, 2), "Bob")

    def test_field_data_or_none(self) -> None:
        self.assertIsNone(self.core.field_data_or_none(self.f1))
        self.core.set_value(self.f1, 1, "X")
        self.assertIsNotNone(self.core.field_data_or_none(self.f1))

    def test_update_batch(self) -> None:
        self.core.update_batch(self.f1, (1, 2, 3), "same")
        for i in (1, 2, 3):
            self.assertEqual(self.core.get_value(self.f1, i), "same")

    def test_insert_if_absent(self) -> None:
        self.core.set_value(self.f1, 1, "keep")
        self.core.insert_if_absent(self.f1, [1, 2], ["overwrite", "new"])
        self.assertEqual(self.core.get_value(self.f1, 1), "keep")
        self.assertEqual(self.core.get_value(self.f1, 2), "new")

    def test_pop_value(self) -> None:
        self.core.set_value(self.f1, 1, "val")
        self.assertEqual(self.core.pop_value(self.f1, 1), "val")
        self.assertIsNone(self.core.get_value(self.f1, 1))

    def test_pop_value_default(self) -> None:
        self.assertEqual(self.core.pop_value(self.f1, 999, "miss"), "miss")

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

    def test_iter_dirty_fields(self) -> None:
        self.core.mark_dirty(self.f1, [1])
        self.core.mark_dirty(self.f2, [2])
        dirty_fields = set(self.core.iter_dirty_fields())
        self.assertEqual(dirty_fields, {self.f1, self.f2})

    # -- patches --

    def test_add_and_get_patches(self) -> None:
        self.core.add_patch(self.f1, 1, 100)
        self.core.add_patch(self.f1, 1, 101)
        patches = self.core.get_patches(self.f1)
        self.assertEqual(patches[1], [100, 101])

    def test_get_patches_none(self) -> None:
        self.assertIsNone(self.core.get_patches(self.f1))

    # -- invalidation --

    def test_invalidate_field_all(self) -> None:
        self.core.set_value(self.f1, 1, "a")
        self.core.set_value(self.f1, 2, "b")
        self.core.invalidate_field(self.f1)
        self.assertIsNone(self.core.get_value(self.f1, 1))

    def test_invalidate_field_specific_ids(self) -> None:
        self.core.set_value(self.f1, 1, "a")
        self.core.set_value(self.f1, 2, "b")
        self.core.invalidate_field(self.f1, [1])
        self.assertIsNone(self.core.get_value(self.f1, 1))
        self.assertEqual(self.core.get_value(self.f1, 2), "b")

    def test_invalidate_all(self) -> None:
        self.core.set_value(self.f1, 1, "a")
        self.core.set_value(self.f2, 1, "b")
        self.core.invalidate_all()
        self.assertIsNone(self.core.get_value(self.f1, 1))
        self.assertIsNone(self.core.get_value(self.f2, 1))

    # -- iteration --

    def test_iter_fields(self) -> None:
        self.core.set_value(self.f1, 1, "a")
        self.core.set_value(self.f2, 1, "b")
        self.assertEqual(set(self.core.iter_fields()), {self.f1, self.f2})

    def test_iter_field_items(self) -> None:
        self.core.set_value(self.f1, 1, "a")
        items = dict(self.core.iter_field_items())
        self.assertIn(self.f1, items)
        self.assertEqual(items[self.f1][1], "a")

    def test_has_field(self) -> None:
        self.assertFalse(self.core.has_field(self.f1))
        self.core.set_value(self.f1, 1, "a")
        self.assertTrue(self.core.has_field(self.f1))


class TestOrmCoreCompute(unittest.TestCase):
    """Test compute operations through OrmCore."""

    def setUp(self) -> None:
        self.core = OrmCore()
        self.f1 = FakeField("sale.order", "amount")
        self.f2 = FakeField("sale.order", "tax")

    def test_schedule_and_pending(self) -> None:
        self.core.schedule(self.f1, [1, 2])
        self.assertTrue(self.core.has_pending(self.f1))
        self.assertTrue(self.core.has_any_pending())
        self.assertEqual(self.core.pending_ids(self.f1), {1, 2})

    def test_is_pending(self) -> None:
        self.core.schedule(self.f1, [1, 2])
        self.assertTrue(self.core.is_pending(self.f1, 1))
        self.assertFalse(self.core.is_pending(self.f1, 3))

    def test_is_pending_no_schedule(self) -> None:
        self.assertFalse(self.core.is_pending(self.f1, 1))

    def test_has_pending_false(self) -> None:
        self.assertFalse(self.core.has_pending(self.f1))
        self.assertFalse(self.core.has_any_pending())

    def test_pending_ids_empty(self) -> None:
        self.assertEqual(self.core.pending_ids(self.f1), ())

    def test_mark_done(self) -> None:
        self.core.schedule(self.f1, [1, 2, 3])
        self.core.mark_done(self.f1, [1, 2])
        self.assertEqual(self.core.pending_ids(self.f1), {3})

    def test_mark_done_clears_entry(self) -> None:
        self.core.schedule(self.f1, [1])
        self.core.mark_done(self.f1, [1])
        self.assertFalse(self.core.has_pending(self.f1))

    def test_pending_fields(self) -> None:
        self.core.schedule(self.f1, [1])
        self.core.schedule(self.f2, [2])
        self.assertEqual(set(self.core.pending_fields()), {self.f1, self.f2})

    def test_pending_property(self) -> None:
        self.core.schedule(self.f1, [1])
        self.assertIn(self.f1, self.core.pending)

    def test_discard_field(self) -> None:
        self.core.schedule(self.f1, [1, 2])
        self.core.discard_field(self.f1)
        self.assertFalse(self.core.has_pending(self.f1))

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


class TestOrmCoreLifecycle(unittest.TestCase):
    """Test clear/invalidation lifecycle."""

    def setUp(self) -> None:
        self.core = OrmCore()
        self.f1 = FakeField("x", "a")

    def test_clear(self) -> None:
        self.core.set_value(self.f1, 1, "v")
        self.core.mark_dirty(self.f1, [1])
        self.core.schedule(self.f1, [1])
        self.core.clear()
        self.assertIsNone(self.core.get_value(self.f1, 1))
        self.assertFalse(self.core.is_any_dirty())
        self.assertFalse(self.core.has_any_pending())

    def test_clear_cache_only(self) -> None:
        self.core.set_value(self.f1, 1, "v")
        self.core.schedule(self.f1, [1])
        self.core.clear_cache()
        self.assertIsNone(self.core.get_value(self.f1, 1))
        self.assertTrue(self.core.has_pending(self.f1))

    def test_clear_compute_only(self) -> None:
        self.core.set_value(self.f1, 1, "v")
        self.core.schedule(self.f1, [1])
        self.core.clear_compute()
        self.assertEqual(self.core.get_value(self.f1, 1), "v")
        self.assertFalse(self.core.has_pending(self.f1))


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
    component access — the facade must be transparent.
    """

    def setUp(self) -> None:
        self.cache = FieldCache()
        self.engine = ComputeEngine()
        self.core = OrmCore(cache=self.cache, engine=self.engine)
        self.f1 = FakeField("m", "f")

    def test_field_data_is_same_object(self) -> None:
        self.core.set_value(self.f1, 1, "v")
        self.assertIs(
            self.core.field_data(self.f1),
            self.cache.get_field_data(self.f1),
        )

    def test_pending_ids_same_object(self) -> None:
        self.core.schedule(self.f1, [1, 2])
        self.assertIs(
            self.core.pending_ids(self.f1),
            self.engine.pending_ids(self.f1),
        )

    def test_has_pending_matches_engine(self) -> None:
        self.assertEqual(
            self.core.has_pending(self.f1),
            self.engine.has_pending_field(self.f1),
        )
        self.core.schedule(self.f1, [1])
        self.assertEqual(
            self.core.has_pending(self.f1),
            self.engine.has_pending_field(self.f1),
        )

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


if __name__ == "__main__":
    unittest.main()
