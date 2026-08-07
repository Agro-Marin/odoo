import logging
import re
from pathlib import Path

from odoo.modules import Manifest

from . import lint_case

_logger = logging.getLogger(__name__)

import_orm_re = re.compile(r"^(from|import)\s+odoo\.orm", flags=re.MULTILINE)


class TestDunderinit(lint_case.LintCase):
    def test_addons_orm_import(self):
        for manifest in Manifest.all_addon_manifests():
            module_path = Path(manifest.path)
            for path in module_path.rglob("**/*.py"):
                if "tests" in path.relative_to(module_path).parts:
                    continue
                if import_orm_re.search(path.read_text()):
                    self.fail(
                        f"Do not import directly from odoo.orm, use odoo.(api,fields,models): {path}"
                    )
