"""Pure-Python tests for UnitOfWork — no Odoo, no database required.

Tests the convergence loop, stall detection, and dirty model ordering.
Uses mock field objects with model_name/name attributes.
"""

import unittest
from collections import namedtuple

from odoo.orm.components.cache import FieldCache
from odoo.orm.components.compute import ComputeEngine
from odoo.orm.components.unit_of_work import LoopResult, UnitOfWork

_MockField = namedtuple("_MockField", ["model_name", "name"])


def _field(model_name: str, name: str) -> _MockField:
    """Create a mock field key with model_name and name attributes."""
    return _MockField(model_name, name)


class TestDirtyModels(unittest.TestCase):
    """Test dirty model inspection."""

    def setUp(self) -> None:
        self.cache = FieldCache()
        self.engine = ComputeEngine()
        self.uow = UnitOfWork(self.cache, self.engine)

    def test_no_dirty(self) -> None:
        self.assertEqual(self.uow.dirty_models(), [])

    def test_single_dirty_field(self) -> None:
        f = _field("sale.order", "amount_total")
        self.cache.set_value(f, 1, 100)
        self.cache.mark_dirty(f, [1])
        self.assertEqual(self.uow.dirty_models(), ["sale.order"])

    def test_multiple_dirty_models(self) -> None:
        f1 = _field("sale.order", "amount")
        f2 = _field("account.move", "total")
        self.cache.set_value(f1, 1, 100)
        self.cache.mark_dirty(f1, [1])
        self.cache.set_value(f2, 2, 200)
        self.cache.mark_dirty(f2, [2])
        models = self.uow.dirty_models()
        self.assertEqual(len(models), 2)
        self.assertIn("sale.order", models)
        self.assertIn("account.move", models)

    def test_unique_models(self) -> None:
        f1 = _field("sale.order", "amount")
        f2 = _field("sale.order", "state")
        self.cache.set_value(f1, 1, 100)
        self.cache.mark_dirty(f1, [1])
        self.cache.set_value(f2, 1, "draft")
        self.cache.mark_dirty(f2, [1])
        self.assertEqual(self.uow.dirty_models(), ["sale.order"])


class TestConvergenceDetection(unittest.TestCase):
    """Test convergence / stall detection methods."""

    def setUp(self) -> None:
        self.cache = FieldCache()
        self.engine = ComputeEngine()
        self.uow = UnitOfWork(self.cache, self.engine)

    def test_empty_snapshot(self) -> None:
        snap = self.uow.recompute_snapshot()
        self.assertEqual(snap, frozenset())

    def test_snapshot_with_pending(self) -> None:
        f = _field("m", "total")
        self.engine.schedule(f, [1, 2, 3])
        snap = self.uow.recompute_snapshot()
        self.assertEqual(snap, frozenset({(f, 3)}))

    def test_convergence_first_iteration(self) -> None:
        """First iteration (prev=None) always progresses."""
        snap = frozenset({("f", 3)})
        progressing, stalled = self.uow.check_convergence(None, snap)
        self.assertTrue(progressing)
        self.assertEqual(stalled, [])

    def test_convergence_changed(self) -> None:
        """Changed snapshot means progress."""
        prev = frozenset({("f", 3)})
        curr = frozenset({("f", 1)})
        progressing, _stalled = self.uow.check_convergence(prev, curr)
        self.assertTrue(progressing)

    def test_convergence_stalled(self) -> None:
        """Same snapshot means stalled."""
        f = _field("m", "total")
        snap = frozenset({(f, 3)})
        progressing, stalled = self.uow.check_convergence(snap, snap)
        self.assertFalse(progressing)
        self.assertEqual(len(stalled), 1)
        self.assertIn("m.total(3)", stalled[0])


class TestRunRecomputeLoop(unittest.TestCase):
    """Test the fixpoint recompute loop."""

    def setUp(self) -> None:
        self.cache = FieldCache()
        self.engine = ComputeEngine()
        self.uow = UnitOfWork(self.cache, self.engine, max_iterations=10)

    def test_no_pending(self) -> None:
        result = self.uow.run_recompute_loop(lambda f: None)
        self.assertTrue(result.converged)
        self.assertEqual(result.iterations, 0)

    def test_single_field_converges(self) -> None:
        f = _field("m", "total")
        self.engine.schedule(f, [1, 2])

        def recompute(field):
            self.cache.set_value(field, 1, 10)
            self.cache.set_value(field, 2, 20)
            self.engine.mark_done(field, [1, 2])

        result = self.uow.run_recompute_loop(recompute)
        self.assertTrue(result.converged)
        self.assertEqual(result.iterations, 1)

    def test_cascading_compute(self) -> None:
        """Field B depends on A — computing A schedules B."""
        f_a = _field("m", "subtotal")
        f_b = _field("m", "total")
        self.engine.schedule(f_a, [1])

        def recompute(field):
            if field is f_a:
                self.cache.set_value(f_a, 1, 100)
                self.engine.mark_done(f_a, [1])
                # Computing A triggers B
                self.engine.schedule(f_b, [1])
            elif field is f_b:
                self.cache.set_value(f_b, 1, 110)
                self.engine.mark_done(f_b, [1])

        result = self.uow.run_recompute_loop(recompute)
        self.assertTrue(result.converged)
        self.assertEqual(result.iterations, 2)

    def test_max_iterations_non_convergent(self) -> None:
        """Non-convergent compute triggers max iterations."""
        f = _field("m", "cycle")
        self.engine.schedule(f, [1])
        uow = UnitOfWork(self.cache, self.engine, max_iterations=3)

        def recompute(field):
            # Always re-schedule — never converges
            self.engine.mark_done(field, [1])
            self.engine.schedule(field, [1])

        result = uow.run_recompute_loop(recompute)
        self.assertFalse(result.converged)
        self.assertEqual(result.iterations, 3)

    def test_only_real_ids_count(self) -> None:
        """Fields with only falsy (new record) IDs don't count as pending."""
        f = _field("m", "total")
        self.engine.schedule(f, [0])  # falsy ID = new record
        result = self.uow.run_recompute_loop(lambda field: None)
        self.assertTrue(result.converged)
        self.assertEqual(result.iterations, 0)


class TestRunFlushLoop(unittest.TestCase):
    """Test the outer flush loop (recompute → flush → repeat)."""

    def setUp(self) -> None:
        self.cache = FieldCache()
        self.engine = ComputeEngine()
        self.uow = UnitOfWork(self.cache, self.engine, max_iterations=10)

    def test_no_dirty(self) -> None:
        result = self.uow.run_flush_loop(
            recompute_fn=lambda f: None,
            flush_fn=lambda models: None,
        )
        self.assertTrue(result.converged)
        self.assertEqual(result.iterations, 0)

    def test_single_flush(self) -> None:
        f = _field("sale.order", "amount")
        self.cache.set_value(f, 1, 100)
        self.cache.mark_dirty(f, [1])
        flushed_models = []

        def flush(models):
            flushed_models.extend(models)
            # Simulate flush: clear dirty
            self.cache.pop_dirty(f)

        result = self.uow.run_flush_loop(
            recompute_fn=lambda field: None,
            flush_fn=flush,
        )
        self.assertTrue(result.converged)
        self.assertEqual(flushed_models, ["sale.order"])

    def test_flush_triggers_recompute(self) -> None:
        """Flush can trigger new computations (via modified())."""
        f_amount = _field("sale.order", "amount")
        f_tax = _field("sale.order", "tax")
        self.cache.set_value(f_amount, 1, 100)
        self.cache.mark_dirty(f_amount, [1])
        flush_count = [0]

        def recompute(field):
            # compute tax when scheduled
            self.cache.set_value(field, 1, 10)
            self.engine.mark_done(field, [1])
            self.cache.mark_dirty(field, [1])

        def flush(models):
            flush_count[0] += 1
            # First flush: clear amount dirty, schedule tax recompute
            if flush_count[0] == 1:
                self.cache.pop_dirty(f_amount)
                self.engine.schedule(f_tax, [1])
            else:
                # Second flush: clear tax dirty
                self.cache.pop_dirty(f_tax)

        result = self.uow.run_flush_loop(
            recompute_fn=recompute,
            flush_fn=flush,
        )
        self.assertTrue(result.converged)
        self.assertEqual(flush_count[0], 2)

    def test_iterations_count_working_passes_only(self) -> None:
        """LoopResult.iterations convention: passes that recomputed or flushed
        count (fully or partially executed); the final nothing-to-do pass does
        not. A pass whose inner recompute loop runs but that flushes nothing
        must therefore count as one iteration."""
        f = _field("m", "total")
        self.engine.schedule(f, [1])

        def recompute(field):
            # computes without dirtying anything
            self.cache.set_value(field, 1, 10)
            self.engine.mark_done(field, [1])

        result = self.uow.run_flush_loop(
            recompute_fn=recompute,
            flush_fn=lambda models: self.fail("nothing dirty, must not flush"),
        )
        self.assertTrue(result.converged)
        self.assertEqual(result.iterations, 1)

    def test_iterations_zero_when_nothing_to_do(self) -> None:
        result = self.uow.run_flush_loop(
            recompute_fn=lambda f: None,
            flush_fn=lambda models: None,
        )
        self.assertTrue(result.converged)
        self.assertEqual(result.iterations, 0)

    def test_iterations_count_flush_passes(self) -> None:
        """Two flushing passes -> iterations == 2 (the closing empty pass is
        not counted)."""
        f1 = _field("m", "a")
        f2 = _field("m", "b")
        self.cache.mark_dirty(f1, [1])
        calls = [0]

        def flush(models):
            calls[0] += 1
            if calls[0] == 1:
                self.cache.pop_dirty(f1)
                self.cache.mark_dirty(f2, [1])  # re-dirty -> second pass
            else:
                self.cache.pop_dirty(f2)

        result = self.uow.run_flush_loop(
            recompute_fn=lambda field: None,
            flush_fn=flush,
        )
        self.assertTrue(result.converged)
        self.assertEqual(calls[0], 2)
        self.assertEqual(result.iterations, 2)

    def test_converged_result_has_no_stalled_fields(self) -> None:
        """A loop that stalls transiently then converges must not report stalls.

        Regression: run_flush_loop set stalled_fields on a non-progress
        iteration but never cleared them when it later converged via the
        empty-dirty break, returning the inconsistent (converged=True,
        stalled_fields=[...]) pair.
        """
        f = _field("m", "a")
        self.cache.mark_dirty(f, [1, 2])  # dirty count stays 2 across iter 0->1
        calls = [0]

        def flush(models):
            # iter 0 flush: leave dirty unchanged -> iter 1 sees no progress
            #   (curr_dirty_count >= prev) and records a stall.
            # iter 1 flush: clear dirty -> iter 2 converges via empty break.
            if calls[0] == 1:
                self.cache.pop_dirty(f)
            calls[0] += 1

        result = self.uow.run_flush_loop(
            recompute_fn=lambda field: None,
            flush_fn=flush,
        )
        self.assertTrue(result.converged)
        self.assertEqual(result.stalled_fields, [])

    def test_recompute_non_convergence_propagates(self) -> None:
        """If recompute loop doesn't converge, flush loop breaks early."""
        f = _field("m", "cycle")
        self.engine.schedule(f, [1])
        uow = UnitOfWork(self.cache, self.engine, max_iterations=3)
        flush_called = [False]

        def recompute(field):
            # Never converges: re-schedule after marking done
            self.engine.mark_done(field, [1])
            self.engine.schedule(field, [1])

        def flush(models):
            flush_called[0] = True

        result = uow.run_flush_loop(
            recompute_fn=recompute,
            flush_fn=flush,
        )
        self.assertFalse(result.converged)
        self.assertFalse(
            flush_called[0], "flush should not be called when recompute stalls"
        )
        self.assertTrue(len(result.stalled_fields) > 0)


class TestLoopExhaustionConsistency(unittest.TestCase):
    """Loop exhaustion must report a consistent LoopResult."""

    def test_flush_exhaustion_with_pending_recompute_is_not_converged(self) -> None:
        """A final flush that schedules a recompute must not report converged.

        Otherwise ``flush_all`` returns success while the scheduled computation
        was never run or persisted — silent data loss instead of RuntimeError.
        """
        cache = FieldCache()
        engine = ComputeEngine()
        uow = UnitOfWork(cache, engine, max_iterations=3)
        f_dirty = _field("m", "a")
        f_computed = _field("m", "b")
        cache.set_value(f_dirty, 1, 10)
        cache.mark_dirty(f_dirty, [1])
        state = {"flush": 0}

        def recompute_fn(field):
            engine.mark_done(field, list(engine.pending_ids(field)))

        def flush_fn(_models):
            state["flush"] += 1
            cache.pop_dirty(f_dirty)
            if state["flush"] < uow.max_iterations:
                cache.set_value(f_dirty, state["flush"] + 1, 10)
                cache.mark_dirty(f_dirty, [state["flush"] + 1])
            else:
                engine.schedule(f_computed, [1, 2, 3])  # modified() side effect

        result = uow.run_flush_loop(recompute_fn, flush_fn)
        self.assertFalse(result.converged)
        # the pending-but-not-yet-dirty computed field is reported as stalled
        self.assertIn("m.b", result.stalled_fields)

    def test_recompute_convergence_on_last_iteration_clears_stalled(self) -> None:
        """Converging exactly on the final iteration must not keep stalled_fields."""
        cache = FieldCache()
        engine = ComputeEngine()
        uow = UnitOfWork(cache, engine, max_iterations=3)
        f = _field("m", "total")
        engine.schedule(f, [1])
        state = {"n": 0}

        def recompute_fn(_field):
            state["n"] += 1
            if state["n"] >= 3:  # stall on 0,1; resolve on the last iteration
                engine.mark_done(f, [1])

        result = uow.run_recompute_loop(recompute_fn)
        self.assertFalse(engine.pending_real_fields())
        self.assertTrue(result.converged)
        self.assertEqual(result.stalled_fields, [])


class TestLoopResult(unittest.TestCase):
    """Test LoopResult dataclass."""

    def test_defaults(self) -> None:
        r = LoopResult()
        self.assertEqual(r.iterations, 0)
        self.assertTrue(r.converged)
        self.assertEqual(r.stalled_fields, [])


if __name__ == "__main__":
    unittest.main()
