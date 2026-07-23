"""Recompute-order contract tests: Kahn on the SCC condensation (no Odoo, no DB).

The ``ModelGraph.recompute_order`` contract: for any pair of stored-computed
fields where B (transitively) depends on A and the two are not in the same
dependency cycle, ``order[A] < order[B]``; all fields of one cycle (strongly
connected component) share a single priority. In particular, the acyclic
region *downstream* of a cycle keeps strict topological order — the plain
Kahn drain used before could never reach those nodes and flattened them all
to one max priority (audit finding; characterized by the
``fuzz_recompute_order`` scripts).

Includes a seeded port of the audit's property fuzzer, upgraded to the strict
except-within-SCC property that only holds with the condensation.
"""

import random
import unittest

from odoo.orm.components.model_graph import (
    ModelGraph,
    _strongly_connected_components,
)

from .test_model_graph import MockField


def _sc(name: str) -> MockField:
    """A stored-computed mock field (participates in the ordering)."""
    return MockField(name, store=True, compute="_compute_" + name)


def _reachable(adjacency, src, dst) -> bool:
    stack, seen = [src], set()
    while stack:
        node = stack.pop()
        if node is dst:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adjacency.get(node, ()))
    return False


class TestDownstreamOfCycle(unittest.TestCase):
    """The acyclic region downstream of a cycle keeps strict order."""

    def test_chain_after_cycle_is_strictly_ordered(self) -> None:
        """source → (a ⇄ b) → c → d: cycle shares one priority, c before d."""
        g = ModelGraph()
        source, a, b, c, d = (_sc(n) for n in ["source", "a", "b", "c", "d"])
        g.add_trigger(source, (), [a])
        g.add_trigger(a, (), [b])
        g.add_trigger(b, (), [a, c])  # cycle a<->b, then downstream chain
        g.add_trigger(c, (), [d])

        order = g.recompute_order
        self.assertLess(order[source], order[a])
        self.assertEqual(order[a], order[b])  # one SCC, one priority
        self.assertLess(order[a], order[c])  # downstream of the cycle...
        self.assertLess(order[c], order[d])  # ...stays strictly ordered

    def test_two_cycles_in_sequence(self) -> None:
        """(a ⇄ b) → (c ⇄ d) → e: SCCs order strictly among themselves."""
        g = ModelGraph()
        a, b, c, d, e = (_sc(n) for n in ["a", "b", "c", "d", "e"])
        g.add_trigger(a, (), [b])
        g.add_trigger(b, (), [a, c])
        g.add_trigger(c, (), [d])
        g.add_trigger(d, (), [c, e])

        order = g.recompute_order
        self.assertEqual(order[a], order[b])
        self.assertEqual(order[c], order[d])
        self.assertLess(order[a], order[c])
        self.assertLess(order[c], order[e])

    def test_self_loop_is_a_singleton_cycle(self) -> None:
        """a → a → b: the self-loop does not break ordering of its dependents.

        (Self-edges are dropped when building adjacency — ``target is not
        dep_field`` — so a self-dependent field is a plain singleton node.)
        """
        g = ModelGraph()
        a, b = _sc("a"), _sc("b")
        g.add_trigger(a, (), [a, b])
        order = g.recompute_order
        self.assertLess(order[a], order[b])


class TestSeededFuzzProperties(unittest.TestCase):
    """Seeded port of the audit's recompute-order property fuzzer.

    Strict property (only achievable with the SCC condensation): every
    trigger edge between ordered fields in *different* SCCs is strictly
    ordered; fields in the *same* SCC share a priority.
    """

    N_TRIALS = 300

    def test_seeded_random_graphs(self) -> None:
        for trial in range(self.N_TRIALS):
            rng = random.Random(trial)
            n = rng.randint(2, 12)
            fields = [_sc(f"f{i}") for i in range(n)]
            # a few non-stored / non-computed fields mixed in
            others = [
                MockField(f"ns{i}", store=False, compute="_c") for i in range(2)
            ] + [MockField(f"col{i}", store=True) for i in range(2)]
            pool = fields + others

            g = ModelGraph()
            edges: list[tuple[MockField, MockField]] = []
            for _ in range(rng.randint(1, 24)):
                dep = rng.choice(pool)
                targets = rng.sample(pool, rng.randint(1, 3))
                g.add_trigger(dep, (), targets)
                edges.extend((dep, t) for t in targets)

            order = g.recompute_order

            stored_computed = set(fields)
            adjacency: dict = {}
            for dep, target in edges:
                if (
                    dep in stored_computed
                    and target in stored_computed
                    and dep is not target
                ):
                    adjacency.setdefault(dep, set()).add(target)

            with self.subTest(trial=trial):
                # every stored-computed trigger target is ordered
                for _dep, target in edges:
                    if target.store and target.compute:
                        self.assertIn(target, order)
                # strict order across SCCs, equal priority within one SCC
                for dep, target in edges:
                    if dep not in order or target not in order or dep is target:
                        continue
                    same_scc = _reachable(adjacency, dep, target) and _reachable(
                        adjacency, target, dep
                    )
                    if same_scc:
                        self.assertEqual(order[dep], order[target])
                    else:
                        self.assertLess(order[dep], order[target])


class TestStronglyConnectedComponents(unittest.TestCase):
    """Unit tests for the iterative Tarjan helper."""

    def test_acyclic_graph_yields_singletons(self) -> None:
        a, b, c = "a", "b", "c"
        components = _strongly_connected_components({a: {b}, b: {c}, c: set()})
        self.assertEqual(sorted(map(len, components)), [1, 1, 1])

    def test_cycle_is_one_component(self) -> None:
        a, b, c = "a", "b", "c"
        components = _strongly_connected_components({a: {b}, b: {c}, c: {a}})
        self.assertEqual([sorted(comp) for comp in components], [["a", "b", "c"]])

    def test_two_cycles_and_bridge(self) -> None:
        adjacency = {
            "a": {"b"},
            "b": {"a", "c"},
            "c": {"d"},
            "d": {"c"},
        }
        components = {
            frozenset(comp) for comp in _strongly_connected_components(adjacency)
        }
        self.assertEqual(components, {frozenset({"a", "b"}), frozenset({"c", "d"})})

    def test_deep_chain_does_not_recurse(self) -> None:
        """The explicit work stack handles chains far beyond the recursion limit."""
        n = 20000
        adjacency = {i: {i + 1} for i in range(n)}
        adjacency[n] = set()
        components = _strongly_connected_components(adjacency)
        self.assertEqual(len(components), n + 1)


if __name__ == "__main__":
    unittest.main()
