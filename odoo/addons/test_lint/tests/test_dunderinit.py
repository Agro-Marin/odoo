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
        """A module without ``__init__.py`` is not packaged.

        Scoped to this repository, like every other file-based gate here, and
        collected rather than asserted one module at a time: a bare
        ``assertTrue`` in the loop stops at the first offender, so the count in
        the log was never the number of modules with the problem.
        """
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
            0,
            "module(s) without an `__init__.py`",
            "Add one, or the module ships without its Python.",
        )
