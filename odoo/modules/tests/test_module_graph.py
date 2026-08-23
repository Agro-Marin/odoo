import unittest
from unittest.mock import patch

from odoo.modules.module import _DEFAULT_MANIFEST, Manifest
from odoo.modules.module_graph import ModuleGraph, ModuleNode
from odoo.tools import OrderedSet, mute_logger

BaseCase = unittest.TestCase


class TestGraph(BaseCase):
    @mute_logger("odoo.modules.module_graph")
    def _test_graph_order(
        self,
        dependency: dict[str, list[str]],
        modules_list: list[list[str]],
        expected: list[str],
    ) -> None:

        def make_manifest(name, **kw):
            if name not in dependency:
                return None
            return Manifest(
                path="/dummy/" + name,
                manifest_content=dict(
                    _DEFAULT_MANIFEST,
                    author="test",
                    license="LGPL-3",
                    depends=dependency.get(name, []),
                ),
            )

        with (
            patch("odoo.modules.module_graph.ModuleGraph._update_from_database"),
            patch("odoo.modules.module_graph.Manifest.for_addon", make_manifest),
            patch(
                "odoo.modules.module_graph.ModuleGraph._imported_modules",
                {"studio_customization"},
            ),
        ):
            dummy_cr = None
            graph = ModuleGraph(dummy_cr)

            for modules in modules_list:
                graph.extend(modules)

            names = [p.name for p in graph]
            self.assertListEqual(names, expected)

    def test_graph_order_1(self):
        dependency = {
            "base": [],
            "module1": ["base"],
            "module2": ["module1"],
            "module3": ["module1"],
            "module4": ["module2", "module3"],
            "module5": ["module2", "module4"],
        }
        self._test_graph_order(
            dependency,
            [["base"], ["module3", "module4", "module1", "module5", "module2"]],
            ["base", "module1", "module2", "module3", "module4", "module5"],
        )
        self._test_graph_order(
            dependency,
            [["base"], ["module1", "module2", "module3", "module5"]],
            ["base", "module1", "module2", "module3"],
        )
        self._test_graph_order(
            dependency,
            [
                ["base"],
                [
                    "module1",
                    "module2",
                    "module3",
                    "module4",
                    "module5",
                    "module6",
                ],
            ],
            ["base", "module1", "module2", "module3", "module4", "module5"],
        )
        self._test_graph_order(
            dependency,
            [
                ["base"],
                ["module1", "module2", "module3"],
                ["module4", "module5"],
            ],
            ["base", "module1", "module2", "module3", "module4", "module5"],
        )

    def test_graph_order_2(self):
        dependency = {
            "base": [],
            "module1": ["base"],
            "module2": ["module1"],
            "module3": ["module1"],
            "module4": ["module3"],
            "module5": ["module2"],
        }
        self._test_graph_order(
            dependency,
            [["base"], ["module3", "module4", "module1", "module5", "module2"]],
            ["base", "module1", "module2", "module3", "module4", "module5"],
        )

    def test_graph_order_3(self):
        dependency = {
            "base": [],
            "module1": ["base"],
            "module2": ["module1"],
            "module3": ["module1", "module5"],
            "module4": ["module2", "module3"],
            "module5": ["module2", "module4"],
        }
        self._test_graph_order(
            dependency,
            [["base"], ["module3", "module4", "module1", "module5", "module2"]],
            ["base", "module1", "module2"],
        )

    def test_graph_order_shared_cycle_members_removed(self):
        dependency = {
            "base": [],
            "module1": ["base"],
            "a": ["base", "b", "c"],
            "b": ["d"],
            "c": ["d"],
            "d": ["a"],
        }
        self._test_graph_order(
            dependency,
            [["base"], ["module1", "a", "b", "c", "d"]],
            ["base", "module1"],
        )

    def test_graph_order_with_test_modules(self):
        dependency = {
            "base": [],
            "module1": ["base"],
            "test_z": ["base"],
            "test_a": ["test_z"],
            "module2": ["module1"],
            "module3": ["module1"],
            "module4": ["module2", "module3"],
            "test_c": ["module1"],
            "test_b": ["test_z", "module4"],
        }
        self._test_graph_order(
            dependency,
            [
                ["base"],
                [
                    "test_c",
                    "module4",
                    "module2",
                    "test_a",
                    "module3",
                    "test_b",
                    "module1",
                    "test_z",
                ],
            ],
            [
                "base",
                "test_z",
                "test_a",
                "module1",
                "test_c",
                "module2",
                "module3",
                "module4",
                "test_b",
            ],
        )


class TestCycleDetection(BaseCase):
    @staticmethod
    def _graph(edges: dict[str, list[str]]) -> ModuleGraph:
        graph = ModuleGraph.__new__(ModuleGraph)
        graph._modules = {}
        graph.mode = "load"
        graph._cr = None
        nodes = {}
        for name in edges:
            node = ModuleNode.__new__(ModuleNode)
            node.name = name
            node.module_graph = graph
            nodes[name] = node
            graph._modules[name] = node
        for name, deps in edges.items():
            nodes[name].depends = OrderedSet(nodes[d] for d in deps)
        return graph

    def test_shared_node_two_cycles(self):
        graph = self._graph({"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": ["a"]})
        self.assertEqual(graph._find_cycle_members(), {"a", "b", "c", "d"})

    def test_acyclic_graph_has_no_members(self):
        graph = self._graph({"base": [], "a": ["base"], "b": ["a", "base"]})
        self.assertEqual(graph._find_cycle_members(), set())

    def test_self_loop_is_a_cycle(self):
        graph = self._graph({"x": ["x"], "y": ["x"]})
        self.assertEqual(graph._find_cycle_members(), {"x"})

    def test_simple_two_cycle_leaves_dependents_clean(self):
        graph = self._graph({"p": ["q"], "q": ["p"], "r": ["p"]})
        self.assertEqual(graph._find_cycle_members(), {"p", "q"})

    @mute_logger("odoo.modules.module_graph")
    def test_update_from_database_skips_cascaded_removed_module(self):
        graph = self._graph({"a": [], "b": ["a"]})

        class _Cursor:
            rows = [
                ("a", 1, "uninstallable", False, "1.0"),
                ("b", 2, "uninstallable", False, "1.0"),
            ]

            def execute(self, query, params):
                pass

            def fetchall(self):
                return self.rows

        graph._cr = _Cursor()
        graph._update_from_database(["a", "b"])
        self.assertNotIn("a", graph)
        self.assertNotIn("b", graph)
