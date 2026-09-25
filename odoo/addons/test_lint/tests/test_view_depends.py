from collections import defaultdict

from odoo.modules import Manifest
from odoo.modules.registry import Registry
from odoo.tests.common import get_db_name

from .lint_case import LintCase, repo_of

REPOS = ("odoo", "enterprise", "agromarin")


class TestViewDepends(LintCase):
    def test_every_sql_view_model_names_the_fields_its_sql_reads(self):
        registry = Registry(get_db_name())
        by_repo: dict[str, list[str]] = defaultdict(list)
        with registry.cursor() as cr:
            try:
                undeclared = registry.get_undeclared_view_reads(cr, list(registry))
            finally:
                cr.rollback()
        for name, missing in undeclared.items():
            manifest = Manifest.for_addon(registry[name]._original_module)
            repo = repo_of(manifest.path) if manifest else "odoo"
            by_repo[repo].append(
                f"{name} ({registry[name]._original_module}): {', '.join(missing)}"
            )
        for repo in REPOS:
            with self.subTest(repo=repo):
                self.assert_ratchet(
                    by_repo[repo],
                    f"view_depends_undeclared_{repo}",
                    "SQL view model(s) reading stored fields their _depends does not name",
                    "A search on the view flushes only what _depends names, so a "
                    "value written in the same transaction reads as its previous "
                    "one (NULL for a stored compute not yet written). Name every "
                    "field the SQL reads in _depends, as account.invoice.report does.",
                )
