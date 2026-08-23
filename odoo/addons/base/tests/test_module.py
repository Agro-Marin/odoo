from odoo.modules.db import (
    _AUTO_INSTALL_CANDIDATES_QUERY,
    _AUTO_INSTALL_CLOSURE_QUERY,
    create_categories,
)
from odoo.tests.common import TransactionCase


class TestAutoInstallQueries(TransactionCase):
    PREFIX = "_audit_ai_"

    def _add_module(self, name, state, auto_install=False):
        self.cr.execute(
            "INSERT INTO ir_module_module (name, state, auto_install)"
            " VALUES (%s, %s, %s) RETURNING id",
            (self.PREFIX + name, state, auto_install),
        )
        return self.cr.fetchone()[0]

    def _add_dep(self, module_id, dep_name, required):
        self.cr.execute(
            "INSERT INTO ir_module_module_dependency"
            " (module_id, name, auto_install_required) VALUES (%s, %s, %s)",
            (module_id, self.PREFIX + dep_name, required),
        )

    def _fixture_rows(self, rows):
        return {name for (name,) in rows if name.startswith(self.PREFIX)}

    def test_candidate_selection(self):
        self._add_module("marked_dep", "to install")
        self._add_module("unmarked_dep", "uninstalled")
        self._add_module("uninst_dep", "uninstallable")

        ok = self._add_module("cand_ok", "uninstalled", auto_install=True)
        self._add_dep(ok, "marked_dep", required=True)

        blocked_req = self._add_module(
            "cand_blocked_required", "uninstalled", auto_install=True
        )
        self._add_dep(blocked_req, "unmarked_dep", required=True)

        blocked_missing = self._add_module(
            "cand_blocked_missing", "uninstalled", auto_install=True
        )
        self._add_dep(blocked_missing, "marked_dep", required=True)
        self._add_dep(blocked_missing, "no_such_module", required=False)

        blocked_uninst = self._add_module(
            "cand_blocked_uninst", "uninstalled", auto_install=True
        )
        self._add_dep(blocked_uninst, "marked_dep", required=True)
        self._add_dep(blocked_uninst, "uninst_dep", required=False)

        self.cr.execute(_AUTO_INSTALL_CANDIDATES_QUERY)
        selected = self._fixture_rows(self.cr.fetchall())
        self.assertEqual(selected, {self.PREFIX + "cand_ok"})

    def test_closure_selection(self):
        self._add_module("plain_dep", "uninstalled")
        self._add_module("uninst_dep", "uninstallable")
        self._add_module("marked_dep", "to install")
        m1 = self._add_module("installing", "to install")
        self._add_dep(m1, "plain_dep", required=False)
        self._add_dep(m1, "uninst_dep", required=False)
        self._add_dep(m1, "marked_dep", required=False)

        self._add_module("plain_dep2", "uninstalled")
        m2 = self._add_module("candidate", "uninstalled")
        self._add_dep(m2, "plain_dep2", required=False)

        candidates = [self.PREFIX + "candidate"]
        self.cr.execute(_AUTO_INSTALL_CLOSURE_QUERY, [candidates, candidates])
        pulled = self._fixture_rows(self.cr.fetchall())
        self.assertEqual(
            pulled, {self.PREFIX + "plain_dep", self.PREFIX + "plain_dep2"}
        )


class TestCreateCategoriesCache(TransactionCase):
    def test_warm_cache_short_circuits_queries(self):
        cache = {}
        cat_id = create_categories(self.cr, ["Audit Cat", "Sub"], cache)
        self.assertIsInstance(cat_id, int)
        queries_before = self.cr.sql_log_count
        again = create_categories(self.cr, ["Audit Cat", "Sub"], cache)
        self.assertEqual(again, cat_id)
        self.assertEqual(self.cr.sql_log_count, queries_before, "expected 0 queries")

    def test_without_cache_behaviour_unchanged(self):
        cat_id = create_categories(self.cr, ["Audit Cat", "Sub"])
        self.assertEqual(create_categories(self.cr, ["Audit Cat", "Sub"]), cat_id)
