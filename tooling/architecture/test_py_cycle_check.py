#!/usr/bin/env python3


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
        report = pcc.check()
        self.assertGreater(report.modules, 200, "core modules not found")
        self.assertGreater(report.edges, 500, "no import edges resolved")

    def test_the_orm_is_acyclic(self):

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


class TestTestFrameworkIsInTheGraph(unittest.TestCase):
    FRAMEWORK = (
        "odoo.tests.common",
        "odoo.tests.case",
        "odoo.tests.loader",
        "odoo.tests.http",
        "odoo.tests.suite",
        "odoo.tests.tag_selector",
    )

    def test_framework_modules_are_in_the_graph(self):
        modules, _edges, _lines = pcc.build_graph()
        missing = [m for m in self.FRAMEWORK if m not in modules]
        self.assertEqual(missing, [], f"test framework modules dropped: {missing}")

    def test_the_frameworks_own_tests_are_still_excluded(self):
        modules, _edges, _lines = pcc.build_graph()
        for name in ("odoo.tests.test_cursor", "odoo.tests.test_module_operations"):
            with self.subTest(name=name):
                self.assertNotIn(name, modules)

    def test_ordinary_test_packages_are_still_dropped(self):
        modules, _edges, _lines = pcc.build_graph()
        leaked = [
            m for m in modules if ".tests." in m and not m.startswith("odoo.tests")
        ]
        self.assertEqual(leaked[:5], [], "a real test suite leaked into the graph")

    def test_is_test_file_rule(self):
        self.assertFalse(pcc._is_test_file(("tests", "common.py"), "common.py"))
        self.assertTrue(
            pcc._is_test_file(("tests", "test_cursor.py"), "test_cursor.py")
        )
        self.assertTrue(pcc._is_test_file(("orm", "tests", "x.py"), "x.py"))
        self.assertTrue(pcc._is_test_file(("orm", "conftest.py"), "conftest.py"))
        self.assertFalse(pcc._is_test_file(("orm", "fields", "base.py"), "base.py"))

    def test_excluded_subpackages_match_only_at_the_top_level(self):

        self.assertNotIn("odoo.tools", str(pcc.EXCLUDED_SUBPACKAGES))
        modules, _edges, _lines = pcc.build_graph()
        self.assertTrue(any(m.startswith("odoo.tools") for m in modules))


class TestScanIsWiderThanBefore(unittest.TestCase):
    def test_module_count_includes_the_framework(self):
        report = pcc.check()
        self.assertGreaterEqual(
            report.modules,
            330,
            "the graph shrank — odoo/tests/ was probably dropped again",
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
