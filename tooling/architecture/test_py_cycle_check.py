#!/usr/bin/env python3
"""Self-test for ``py_cycle_check.py``.

A cycle gate that cannot detect a cycle is decoration, and this one has two ways
to be quietly wrong, both pinned below:

* **Counting a deferred import.** A function-local import is the sanctioned way
  to break a cycle in Python. If the collector counted it, the gate would report
  the framework as tangled exactly where it has been *untangled* — and every
  seam that exists to fix this problem would look like the problem.
* **Missing a real cycle**, or reporting one that is not there. Tarjan is easy
  to get subtly wrong on self-loops and on nested components, so both are tested
  against hand-built graphs rather than only against the live tree.

``TestPinsAreLive`` covers the third failure mode, which is the one that rots
silently: a pinned cycle that has since been broken keeps the gate green while
claiming debt that no longer exists.

Run directly (``python tooling/architecture/test_py_cycle_check.py``) or under
pytest.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import py_cycle_check as pcc


def _imports(src: str, module: str = "pkg.mod", is_init: bool = False) -> list[str]:
    collector = pcc._ModuleLevelImports(module, is_init)
    collector.visit(ast.parse(src))
    return [target for target, _ in collector.found]


class TestEdgeCollection(unittest.TestCase):
    def test_module_level_import_is_an_edge(self):
        self.assertIn("a.b", _imports("from a.b import C\n"))
        self.assertIn("a.b", _imports("import a.b\n"))

    def test_function_local_import_is_not_an_edge(self):
        """The deferred-import seam must not be reported as coupling."""
        self.assertEqual(
            _imports("def f():\n    from a.b import C\n    return C\n"), []
        )

    def test_method_local_import_is_not_an_edge(self):
        src = (
            "class K:\n    def m(self):\n        from a.b import C\n        return C\n"
        )
        self.assertEqual(_imports(src), [])

    def test_type_checking_import_is_not_an_edge(self):
        src = (
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from a.b import C\n"
        )
        self.assertNotIn("a.b", _imports(src))

    def test_else_branch_of_type_checking_is_kept(self):
        src = (
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from a import X\n"
            "else:\n"
            "    from b import Y\n"
        )
        found = _imports(src)
        self.assertNotIn("a", found)
        self.assertIn("b", found)

    def test_relative_import_resolves_against_the_package(self):
        self.assertIn(
            "odoo.orm.models",
            _imports("from ..models import X\n", module="odoo.orm.fields.base"),
        )

    def test_relative_import_in_init_stays_inside_the_package(self):
        self.assertIn(
            "odoo.libs.collections",
            _imports("from .collections import X\n", module="odoo.libs", is_init=True),
        )


class TestCycleDetection(unittest.TestCase):
    @staticmethod
    def _sccs(edges):
        return {
            tuple(sorted(c))
            for c in pcc.strongly_connected(set(edges), edges)
            if len(c) > 1
        }

    def test_finds_a_two_module_cycle(self):
        edges = {"a": {"b"}, "b": {"a"}}
        self.assertEqual(self._sccs(edges), {("a", "b")})

    def test_finds_a_longer_cycle(self):
        edges = {"a": {"b"}, "b": {"c"}, "c": {"a"}}
        self.assertEqual(self._sccs(edges), {("a", "b", "c")})

    def test_a_dag_has_no_cycle(self):
        edges = {"a": {"b", "c"}, "b": {"c"}, "c": set()}
        self.assertEqual(self._sccs(edges), set())

    def test_two_independent_cycles_are_reported_separately(self):
        edges = {"a": {"b"}, "b": {"a"}, "x": {"y"}, "y": {"x"}, "z": {"a", "x"}}
        self.assertEqual(self._sccs(edges), {("a", "b"), ("x", "y")})

    def test_a_shared_node_does_not_merge_distinct_cycles(self):
        # b is reachable from both, but only one component is cyclic.
        edges = {"a": {"b"}, "b": {"a"}, "c": {"b"}}
        self.assertEqual(self._sccs(edges), {("a", "b")})


class TestAgainstTheRealTree(unittest.TestCase):
    def test_the_tree_has_no_new_cycles(self):
        report = pcc.check()
        self.assertEqual(
            [list(c) for c in report.new],
            [],
            "new import cycle — break it, or pin it in KNOWN_CYCLES with a reason",
        )

    def test_it_actually_scanned_something(self):
        """A path typo would make an empty graph look like a clean one."""
        report = pcc.check()
        self.assertGreater(report.modules, 200, "core modules not found")
        self.assertGreater(report.edges, 500, "no import edges resolved")

    def test_the_orm_is_acyclic(self):
        """The most layered subsystem in the tree, and it has no cycles at all.

        Worth asserting rather than only observing: it is the property the whole
        four-layer decomposition exists to produce.
        """
        report = pcc.check()
        orm_cycles = [
            c for c in report.cycles if any(m.startswith("odoo.orm") for m in c)
        ]
        self.assertEqual(orm_cycles, [], "the ORM gained an import cycle")

    def test_addons_are_out_of_scope(self):
        report = pcc.check()
        self.assertTrue(
            all(not m.startswith("odoo.addons") for c in report.cycles for m in c),
            "odoo/addons is the framework's consumer and is governed elsewhere",
        )


class TestPinsAreLive(unittest.TestCase):
    def test_no_stale_pins(self):
        report = pcc.check()
        self.assertEqual(
            [list(c) for c in report.stale_pins],
            [],
            "a pinned cycle no longer exists — remove it (the debt was paid)",
        )

    def test_every_pin_states_a_reason(self):
        for known in pcc.KNOWN_CYCLES:
            with self.subTest(cycle=known.members):
                self.assertGreater(len(known.reason.strip()), 40)

    def test_pinned_members_are_real_modules(self):
        modules, _edges, _lines = pcc.build_graph()
        for known in pcc.KNOWN_CYCLES:
            for member in known.members:
                with self.subTest(member=member):
                    self.assertIn(member, modules)


if __name__ == "__main__":
    unittest.main(verbosity=2)
