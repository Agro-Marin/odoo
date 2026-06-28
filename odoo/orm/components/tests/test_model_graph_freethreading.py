"""Free-threading (PEP 703) stress test for the frozen ModelGraph.

``ModelGraph`` is process-shared (one per registry) and read concurrently by
request-handling threads. Its derived caches used to be filled lazily on first
read, so the first reader *mutated* shared dicts. On free-threaded CPython this
is not a corruption hazard (the dict operations are thread-safe) but it causes
redundant concurrent rebuilds; ``ModelGraph.freeze()`` precomputes the caches so
reads are pure lookups with no rebuild or write.

This test hammers a frozen graph from many threads and asserts (a) no thread
raises, (b) the cache key-sets never grow (the freeze made reads write-free),
and (c) every thread sees identical results. Under the GIL this verifies the
harness and the read-consistency / no-mutation invariant; under a free-threaded
interpreter (``python3.14t``, ``PYTHON_GIL=0`` — see the freethreading CI lane)
it exercises that the frozen read path performs no shared-state mutation under
real parallelism.
"""

import threading
import unittest

from odoo.orm.components.model_graph import ModelGraph

from .test_model_graph import _field


def _representative_graph() -> ModelGraph:
    g = ModelGraph()
    price = _field("price")
    qty = _field("qty")
    partner_id = _field("partner_id", type_="many2one", relational=True)
    total = _field("total", is_stored_computed=True, store=True, compute="_c")
    partner_total = _field(
        "partner_total", is_stored_computed=True, store=True, compute="_c"
    )
    g.add_trigger(price, (), [total])
    g.add_trigger(qty, (), [total])
    g.add_trigger(price, (partner_id,), [partner_total])
    g.add_trigger(total, (), [partner_total])
    g._inverses[partner_id] = (partner_id,)
    return g


class TestModelGraphFreeThreading(unittest.TestCase):
    N_THREADS = 16
    N_ITERATIONS = 500

    def test_concurrent_reads_of_frozen_graph(self) -> None:
        g = _representative_graph()
        g.freeze()

        trigger_fields = list(g._triggers)
        non_trigger = _field("unrelated")
        all_fields = trigger_fields + [non_trigger]

        # Single-threaded reference answers to compare every worker against.
        ref_modrel = {f.name: g.is_modifying_relations(f) for f in all_fields}
        ref_deps = {
            f.name: sorted(d.name for d in g.get_dependent_fields(f))
            for f in all_fields
        }
        ref_order = {f.name: p for f, p in g.recompute_order.items()}

        # The cache key-sets that must NOT change under concurrent reads.
        trees_keys = frozenset(g._trigger_trees)
        modrel_keys = frozenset(g._modifying_relations)
        order_id = id(g._recompute_order)

        errors: list[BaseException] = []
        barrier = threading.Barrier(self.N_THREADS)

        def worker() -> None:
            try:
                barrier.wait()  # maximise overlap
                for _ in range(self.N_ITERATIONS):
                    for f in all_fields:
                        assert g.is_modifying_relations(f) == ref_modrel[f.name]
                        assert (
                            sorted(d.name for d in g.get_dependent_fields(f))
                            == ref_deps[f.name]
                        )
                        g.get_field_trigger_tree(f)
                    g.get_trigger_tree(all_fields)
                    assert {
                        fld.name: p for fld, p in g.recompute_order.items()
                    } == ref_order
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(self.N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"worker(s) raised: {errors[:3]}")
        # No read mutated the shared caches (the freeze guarantee).
        self.assertEqual(frozenset(g._trigger_trees), trees_keys)
        self.assertEqual(frozenset(g._modifying_relations), modrel_keys)
        self.assertEqual(id(g._recompute_order), order_id, "recompute_order replaced")


if __name__ == "__main__":
    unittest.main()
