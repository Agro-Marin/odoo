import tempfile
from pathlib import Path
from unittest.mock import patch

from odoo.modules import neutralize
from odoo.modules.module import Manifest
from odoo.tests import tagged
from odoo.tests.common import BaseCase, TransactionCase

import odoo.addons


@tagged("post_install", "-at_install", "neutralize")
class TestNeutralize(TransactionCase):
    def test_10_neutralize(self):
        """None of the neutralization SQL queries crash."""
        installed_modules = neutralize.get_installed_modules(self.cr)
        queries = neutralize.get_neutralization_queries(installed_modules)
        for query in queries:
            self.cr.execute(query)


class TestNeutralizeQueries(BaseCase):
    """get_neutralization_queries must skip whitespace-only neutralize.sql
    files: an empty string is not a query, and consumers must not need to
    filter it out (psycopg 3 tolerates executing "", so this is a contract
    guarantee, not crash prevention).
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="odoo_test_neutralize_")
        self.addCleanup(self._tmp.cleanup)
        p = patch.object(odoo.addons, "__path__", [self._tmp.name])
        p.start()
        self.addCleanup(p.stop)
        saved = dict(Manifest._manifest_cache)
        Manifest.clear_caches()

        def _restore():
            Manifest._manifest_cache.clear()
            Manifest._manifest_cache.update(saved)

        self.addCleanup(_restore)

    def _make_module(self, name, neutralize_sql=None):
        d = Path(self._tmp.name, name)
        (d / "data").mkdir(parents=True)
        (d / "__manifest__.py").write_text(
            "{'name': 'X', 'license': 'LGPL-3', 'author': 'x'}"
        )
        if neutralize_sql is not None:
            (d / "data" / "neutralize.sql").write_text(neutralize_sql)
        return name

    def test_empty_and_whitespace_files_are_skipped(self):
        modules = [
            self._make_module("probe_empty", ""),
            self._make_module("probe_blank", "  \n\t\n"),
            self._make_module("probe_real", "UPDATE res_users SET active = active;\n"),
            self._make_module("probe_none"),  # no neutralize.sql at all
        ]
        queries = list(neutralize.get_neutralization_queries(modules))
        self.assertEqual(queries, ["UPDATE res_users SET active = active;"])
