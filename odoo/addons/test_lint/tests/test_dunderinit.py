import logging
from pathlib import Path

from odoo.modules import Manifest

from . import lint_case

_logger = logging.getLogger(__name__)

WHITELIST = [
    "test_data_module",
]


class TestDunderinit(lint_case.LintCase):
    def test_dunderinit(self):
        modules_list = [
            mod
            for mod in Manifest.all_addon_manifests()
            if mod.name not in WHITELIST and lint_case.is_core_path(str(mod.path))
        ]
        missing = [
            str(mod.path)
            for mod in modules_list
            if not (Path(mod.path) / "__init__.py").is_file()
        ]

        _logger.info("%s modules checked", len(modules_list))
        self.assertTrue(modules_list, "the scan reached no modules at all")
        self.assert_ratchet(
            missing,
            "lint_module_without_init",
            "module(s) without an `__init__.py`",
            "Add one, or the module ships without its Python.",
        )
