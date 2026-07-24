import logging
import re
from pathlib import Path

from odoo.modules import Manifest

from . import lint_case

_logger = logging.getLogger(__name__)

import_orm_re = re.compile(r"^(from|import)\s+odoo\.orm", flags=re.MULTILINE)


class TestDunderinit(lint_case.LintCase):

    def test_addons_orm_import(self):
        """Addon runtime code must reach the ORM through the public facade
        (odoo.api / odoo.fields / odoo.models), never by importing the unstable
        internal ``odoo.orm`` package directly.

        Test files are exempt by location. Testing an ORM internal necessarily
        imports it, and tests are not shipped API surface, so they carry none of
        the version-drift risk this guard exists to prevent -- exempting them is
        the sole reason the previous per-module allow-list ({base, test_orm,
        test_performance}) existed (none of those modules import odoo.orm in
        runtime code). Skipping tests by path instead of naming modules keeps the
        check self-maintaining (a new ORM-internals test no longer has to be
        remembered here) and, unlike the allow-list, still enforces the rule on
        every module's runtime code, base included.
        """
        for manifest in Manifest.all_addon_manifests():
            module_path = Path(manifest.path)
            for path in module_path.rglob("**/*.py"):
                if "tests" in path.relative_to(module_path).parts:
                    continue
                if import_orm_re.search(path.read_text()):
                    self.fail(
                        f"Do not import directly from odoo.orm, use odoo.(api,fields,models): {path}"
                    )
