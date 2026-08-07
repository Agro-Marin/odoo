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

        ref_modrel = {f.name: g.is_modifying_relations(f) for f in all_fields}
        ref_deps = {
            f.name: sorted(d.name for d in g.get_dependent_fields(f))
            for f in all_fields
        }
        ref_order = {f.name: p for f, p in g.recompute_order.items()}

        trees_keys = frozenset(g._trigger_trees)
        modrel_keys = frozenset(g._modifying_relations)
        order_id = id(g._recompute_order)

        errors: list[BaseException] = []
        barrier = threading.Barrier(self.N_THREADS)

        def worker() -> None:
            try:
                barrier.wait()
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
        self.assertEqual(frozenset(g._trigger_trees), trees_keys)
        self.assertEqual(frozenset(g._modifying_relations), modrel_keys)
        self.assertEqual(id(g._recompute_order), order_id, "recompute_order replaced")


if __name__ == "__main__":
    unittest.main()
