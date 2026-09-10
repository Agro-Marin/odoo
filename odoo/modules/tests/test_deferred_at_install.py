import unittest
from unittest.mock import patch

from odoo.modules.loading import installed_dependents_not_yet_loaded
from odoo.modules.module import _DEFAULT_MANIFEST, Manifest
from odoo.modules.module_graph import ModuleGraph
from odoo.tools import mute_logger


class _NoCursor:
    rowcount = 0

    def execute(self, query, *args, **kwargs):
        raise AssertionError("this test's graph must not reach the database")

    def fetchall(self):
        raise AssertionError("this test's graph must not reach the database")


DEPENDENCY = {
    "base": [],
    "hr": ["base"],
    "hr_work_entry": ["hr"],
    "hr_payroll": ["hr_work_entry"],
    "mail": ["base"],
}


def _make_manifest(name, **kw):
    if name not in DEPENDENCY:
        return None
    return Manifest(
        path="/dummy/" + name,
        manifest_content=dict(
            _DEFAULT_MANIFEST,
            author="test",
            license="LGPL-3",
            depends=DEPENDENCY[name],
        ),
    )


class TestDeferredAtInstall(unittest.TestCase):
    """An at_install suite waits for the installed dependents whose columns the
    table already carries -- and for nothing else."""

    @mute_logger("odoo.modules.module_graph")
    def _graph(self, states):
        with (
            patch("odoo.modules.module_graph.ModuleGraph._update_from_database"),
            patch("odoo.modules.module_graph.Manifest.for_addon", _make_manifest),
            patch(
                "odoo.modules.module_graph.ModuleGraph._imported_modules",
                {"studio_customization"},
            ),
        ):
            graph = ModuleGraph(_NoCursor())
            graph.extend(list(DEPENDENCY))
        for node in graph:
            node.state = states.get(node.name, "installed")
        return graph

    def test_an_installed_dependent_still_to_load_defers(self):
        graph = self._graph({})
        self.assertEqual(
            installed_dependents_not_yet_loaded(graph, "hr", {"base", "hr"}),
            ["hr_work_entry", "hr_payroll"],
        )

    def test_the_closure_is_transitive_and_ordered_by_load_order(self):
        graph = self._graph({})
        self.assertEqual(
            installed_dependents_not_yet_loaded(graph, "base", {"base"}),
            ["hr", "mail", "hr_work_entry", "hr_payroll"],
        )

    def test_a_loaded_dependent_no_longer_counts(self):
        graph = self._graph({})
        loaded = {"base", "hr", "hr_work_entry", "hr_payroll"}
        self.assertEqual(installed_dependents_not_yet_loaded(graph, "hr", loaded), [])

    def test_a_dependent_being_installed_has_no_columns_yet(self):
        # A fresh `-i hr,hr_work_entry`: hr's tests run at install, as before.
        graph = self._graph({"hr_work_entry": "to install", "hr_payroll": "to install"})
        self.assertEqual(
            installed_dependents_not_yet_loaded(graph, "hr", {"base", "hr"}), []
        )

    def test_a_dependent_about_to_upgrade_already_has_its_columns(self):
        # `-u hr` on a database holding hr_work_entry marks both to upgrade.
        graph = self._graph({"hr": "to upgrade", "hr_work_entry": "to upgrade"})
        self.assertEqual(
            installed_dependents_not_yet_loaded(graph, "hr", {"base", "hr"}),
            ["hr_work_entry", "hr_payroll"],
        )

    def test_an_unrelated_module_does_not_count(self):
        graph = self._graph({})
        self.assertEqual(
            installed_dependents_not_yet_loaded(graph, "mail", {"base", "mail"}), []
        )
