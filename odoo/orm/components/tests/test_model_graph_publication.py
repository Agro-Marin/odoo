"""Concurrency tests for ModelGraph's snapshot publication (no Odoo, no DB).

The trigger map and every cache derived from it live in one ``_TriggerState``
snapshot published by a single reference swap; lock-free readers grab one
snapshot per operation. These tests pin:

* the discard_fields reader/writer race regression (an in-place scrub of the
  published map used to crash concurrent tree builds with "dictionary changed
  size during iteration" — reproduced by the audit's ``race_discard_fields``
  script against the pre-snapshot implementation);
* that ``set_triggers`` publishes the map and its derived caches as ONE
  snapshot (structurally, and under reader/writer stress);
* the epoch/barrier protocol (``begin_invalidation``/``end_invalidation``)
  that refuses publication to trigger rebuilds which started before or during
  a registry teardown.
"""

import threading
import unittest

from odoo.orm.components.model_graph import ModelGraph, _empty_triggers

from .test_model_graph import _field

# Enough iterations to interleave reliably; the pre-fix in-place scrub crashed
# well within these bounds on every run of the audit's repro script.
N_WRITER_ITERATIONS = 120


def _staged_map(entries):
    """Build a raw trigger map ``{dep: {path: [targets]}}`` from tuples."""
    staged = _empty_triggers()
    for dep, path, targets in entries:
        bucket = staged[dep][path]
        for target in targets:
            if target not in bucket:
                bucket.append(target)
    return staged


class TestDiscardFieldsRace(unittest.TestCase):
    """Regression: discard_fields must never mutate the published map in place.

    Reader threads build trigger trees (iterating the shared map buckets, as
    ``BaseModel.modified()`` does via ``get_field_trigger_tree`` on a cold
    cache). The writer discards fields and republishes a rebuilt map — the
    production pattern of ``Registry._discard_fields`` (copy-swap + eager
    ``set_triggers`` rebuild). Against the pre-fix in-place scrub this
    reliably raised ``RuntimeError: dictionary changed size during
    iteration`` in a reader.
    """

    N_READERS = 4

    def test_concurrent_discard_and_tree_builds(self) -> None:
        # Sized so the whole test runs in ~1s while still interleaving many
        # thousands of bucket iterations per publication — the pre-fix
        # in-place scrub crashed the audit repro within a handful of writer
        # iterations at comparable sizes.
        n = 150
        fields = [_field(f"f{i}") for i in range(n)]

        def full_entries():
            return [
                (fields[i], (), fields[i + 1 : min(i + 25, n)]) for i in range(n - 1)
            ]

        g = ModelGraph()
        g.set_triggers(_staged_map(full_entries()))
        root = fields[0]
        victims = fields[70:100]

        errors: list[BaseException] = []
        stop = threading.Event()
        barrier = threading.Barrier(self.N_READERS + 1)

        def reader() -> None:
            try:
                barrier.wait()
                while not stop.is_set():
                    # Force a cold tree build every iteration (the audit repro
                    # pattern, simulating a post-invalidation cache): the build
                    # iterates the trigger map's buckets while the writer
                    # discards. clear_caches() is itself a snapshot publication
                    # and safe to issue concurrently.
                    g.clear_caches()
                    tree = g.get_field_trigger_tree(root)
                    for _node in tree.depth_first():
                        pass
            except BaseException as exc:
                errors.append(exc)
                stop.set()

        def writer() -> None:
            try:
                barrier.wait()
                for _ in range(N_WRITER_ITERATIONS):
                    if stop.is_set():
                        return
                    g.discard_fields(victims)
                    # production-faithful rebuild: build locally, publish once
                    g.set_triggers(_staged_map(full_entries()))
            except BaseException as exc:
                errors.append(exc)
            finally:
                stop.set()

        threads = [threading.Thread(target=reader) for _ in range(self.N_READERS)]
        threads.append(threading.Thread(target=writer))
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)

        self.assertEqual(errors, [], f"thread(s) raised: {errors[:3]}")

    def test_discarded_fields_absent_after_discard(self) -> None:
        """Single-threaded semantics: the swap-published map is fully scrubbed."""
        g = ModelGraph()
        dep, gone, kept = _field("dep"), _field("gone"), _field("kept")
        g.set_triggers(_staged_map([(dep, (), [gone, kept]), (gone, (), [kept])]))
        g.discard_fields([gone])
        self.assertFalse(g.has_triggers(gone))
        tree = g.get_trigger_tree([dep])
        self.assertIn(kept, tree.root)
        self.assertNotIn(gone, tree.root)


class TestSnapshotPublication(unittest.TestCase):
    """set_triggers publishes map + derived caches as one atomic snapshot."""

    def test_map_and_derived_caches_are_one_snapshot(self) -> None:
        g = ModelGraph()
        f_old, t_old = _field("price"), _field("total")
        g.set_triggers(_staged_map([(f_old, (), [t_old])]))
        g.get_field_trigger_tree(f_old)  # fill derived caches
        old_trees = g._trigger_trees
        self.assertTrue(old_trees)

        f_new, t_new = _field("name"), _field("display_name")
        staged = _staged_map([(f_new, (), [t_new])])
        g.set_triggers(staged)

        # The published snapshot holds the exact new map with FRESH (not
        # cleared-in-place) derived caches: no window can pair new map with
        # old trees, because they are swapped as one object.
        self.assertIs(g._triggers, staged)
        self.assertIsNot(g._trigger_trees, old_trees)
        self.assertEqual(g._trigger_trees, {})
        self.assertEqual(g._modifying_relations, {})
        self.assertIsNone(g._recompute_order)
        # internal coupling: all introspection views come from one state
        state = g._state
        self.assertIs(state.triggers, g._triggers)
        self.assertIs(state.trees, g._trigger_trees)
        self.assertIs(state.modifying_relations, g._modifying_relations)

    def test_stale_tree_cannot_poison_a_newer_publication(self) -> None:
        """Reader/writer stress: after the final publication, the served tree
        matches the final map.

        Pre-snapshot, a reader computing a tree from map A could store it into
        the cleared shared cache AFTER a concurrent ``set_triggers(B)``,
        permanently serving A's tree against B's map. With per-snapshot tree
        caches this is impossible: a tree computed from state A is only ever
        stored in state A.
        """
        f = _field("f")
        t_a, t_b = _field("target_a"), _field("target_b")
        g = ModelGraph()
        g.set_triggers(_staged_map([(f, (), [t_a])]))

        errors: list[BaseException] = []
        stop = threading.Event()

        def reader() -> None:
            try:
                while not stop.is_set():
                    root = g.get_field_trigger_tree(f).root
                    # Only ever a whole-map view: A's target or B's target.
                    assert root in ((t_a,), (t_b,)), root
            except BaseException as exc:
                errors.append(exc)
                stop.set()

        def writer() -> None:
            try:
                for i in range(N_WRITER_ITERATIONS):
                    if stop.is_set():
                        return
                    target = t_b if i % 2 == 0 else t_a
                    g.set_triggers(_staged_map([(f, (), [target])]))
            except BaseException as exc:
                errors.append(exc)
            finally:
                stop.set()

        threads = [threading.Thread(target=reader) for _ in range(4)]
        threads.append(threading.Thread(target=writer))
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=120)
        self.assertEqual(errors, [], f"thread(s) raised: {errors[:3]}")

        # Final publication wins: no stale tree survives from any older state.
        final_target = g._triggers[f][()][0]
        self.assertEqual(g.get_field_trigger_tree(f).root, (final_target,))

    def test_clear_caches_preserves_map_identity(self) -> None:
        g = ModelGraph()
        staged = _staged_map([(_field("a"), (), [_field("b")])])
        g.set_triggers(staged)
        g.clear_caches()
        self.assertIs(g._triggers, staged)
        self.assertEqual(g._trigger_trees, {})


class TestEpochValidation(unittest.TestCase):
    """begin/end_invalidation refuse stale epoch-validated publications."""

    def _map(self):
        return _staged_map([(_field("a"), (), [_field("b")])])

    def test_current_epoch_publishes(self) -> None:
        g = ModelGraph()
        staged = self._map()
        self.assertTrue(g.set_triggers(staged, epoch=g.trigger_epoch))
        self.assertIs(g._triggers, staged)

    def test_pre_teardown_build_is_refused(self) -> None:
        g = ModelGraph()
        pre_epoch = g.trigger_epoch  # captured before the teardown
        g.begin_invalidation()
        g.end_invalidation()
        published = g._triggers
        self.assertFalse(g.set_triggers(self._map(), epoch=pre_epoch))
        self.assertIs(g._triggers, published, "stale build must not publish")

    def test_mid_teardown_build_is_refused_by_barrier_and_epoch(self) -> None:
        g = ModelGraph()
        g.begin_invalidation()
        mid_epoch = g.trigger_epoch  # captured while models are half set up
        # barrier refuses even a matching epoch during the teardown window
        self.assertFalse(g.set_triggers(self._map(), epoch=mid_epoch))
        g.end_invalidation()
        # after the window the epoch has moved on: still refused, forever
        self.assertFalse(g.set_triggers(self._map(), epoch=mid_epoch))

    def test_post_teardown_build_publishes(self) -> None:
        g = ModelGraph()
        g.begin_invalidation()
        g.end_invalidation()
        staged = self._map()
        self.assertTrue(g.set_triggers(staged, epoch=g.trigger_epoch))
        self.assertIs(g._triggers, staged)

    def test_unvalidated_publish_always_wins(self) -> None:
        """The authoritative writer (no epoch arg) publishes unconditionally,
        even inside a teardown window (it is serialized by the registry lock).
        """
        g = ModelGraph()
        g.begin_invalidation()
        staged = self._map()
        self.assertTrue(g.set_triggers(staged))
        self.assertIs(g._triggers, staged)
        g.end_invalidation()

    def test_epoch_is_monotonic(self) -> None:
        g = ModelGraph()
        e0 = g.trigger_epoch
        g.begin_invalidation()
        e1 = g.trigger_epoch
        g.end_invalidation()
        e2 = g.trigger_epoch
        self.assertLess(e0, e1)
        self.assertLess(e1, e2)


if __name__ == "__main__":
    unittest.main()
