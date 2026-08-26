import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from odoo.modules import neutralize
from odoo.modules.module import Manifest

import odoo.addons

BaseCase = unittest.TestCase


class _Cursor:
    """Executes nothing; raises for the module named in `fail_on`."""

    def __init__(self, fail_on=None, installed=()):
        self.executed = []
        self.fail_on = fail_on
        #: read by fetchall(); it was only ever set from outside, so the double
        #: was a step away from an AttributeError that named nothing
        self.installed = list(installed)

    def execute(self, query, params=None):
        self.executed.append(query)
        if self.fail_on and self.fail_on in query:
            raise ValueError("syntax error at or near")

    def fetchall(self):
        return [(name,) for name in self.installed]


class NeutralizeQueryCase(BaseCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="odoo_test_neutralize_")
        self.addCleanup(self._tmp.cleanup)
        p = patch.object(odoo.addons, "__path__", [self._tmp.name])
        p.start()
        self.addCleanup(p.stop)
        saved = dict(Manifest._parse_cache)
        saved_resolution = dict(Manifest._resolution_cache)
        Manifest.clear_caches()

        def _restore():
            Manifest._parse_cache.clear()
            Manifest._parse_cache.update(saved)
            Manifest._resolution_cache.clear()
            Manifest._resolution_cache.update(saved_resolution)

        self.addCleanup(_restore)

    def _make_module(self, name, neutralize_sql=None):
        d = Path(self._tmp.name, name)
        (d / "data").mkdir(parents=True)
        (d / "__manifest__.py").write_text(
            "{'name': 'X', 'license': 'LGPL-3', 'author': 'x'}", encoding="utf-8"
        )
        if neutralize_sql is not None:
            (d / "data" / "neutralize.sql").write_text(neutralize_sql, encoding="utf-8")
        return name


class TestQueriesCarryTheirModule(NeutralizeQueryCase):
    def test_each_query_is_paired_with_the_module_that_shipped_it(self):
        modules = [
            self._make_module("probe_alpha", "UPDATE a SET x = 1;"),
            self._make_module("probe_no_file"),
            self._make_module("probe_beta", "UPDATE b SET y = 2;"),
        ]
        self.assertEqual(
            list(neutralize.iter_neutralization_queries(modules)),
            [
                ("probe_alpha", "UPDATE a SET x = 1;"),
                ("probe_beta", "UPDATE b SET y = 2;"),
            ],
        )

    def test_the_string_only_view_is_unchanged(self):
        modules = [
            self._make_module("probe_one", "UPDATE a SET x = 1;"),
            self._make_module("probe_two", "  \n\t\n"),
        ]
        self.assertEqual(
            list(neutralize.get_neutralization_queries(modules)),
            ["UPDATE a SET x = 1;"],
        )


class TestAFailingQueryNamesItsModule(NeutralizeQueryCase):
    def test_the_note_names_the_file_the_sql_came_from(self):
        # Each query is a whole .sql file run as one batch, so the driver error
        # on its own cannot say which of the installed modules produced it.
        self._make_module("probe_good", "UPDATE good SET x = 1;")
        self._make_module("probe_bad", "UPDATE broken SET y = 2;")
        cursor = _Cursor(fail_on="broken")
        cursor.installed = ["probe_good", "probe_bad"]

        with self.assertRaises(ValueError) as caught:
            neutralize.neutralize_database(cursor)

        notes = getattr(caught.exception, "__notes__", [])
        self.assertTrue(
            any("probe_bad/data/neutralize.sql" in note for note in notes),
            f"the failure does not name the module it came from: {notes}",
        )
        self.assertFalse(
            any("probe_good" in note for note in notes),
            f"the failure blames a module that succeeded: {notes}",
        )

    def test_a_clean_run_adds_no_note_and_runs_every_query(self):
        self._make_module("probe_a", "UPDATE a SET x = 1;")
        self._make_module("probe_b", "UPDATE b SET y = 2;")
        cursor = _Cursor()
        cursor.installed = ["probe_a", "probe_b"]
        neutralize.neutralize_database(cursor)
        self.assertEqual(
            cursor.executed[1:], ["UPDATE a SET x = 1;", "UPDATE b SET y = 2;"]
        )
