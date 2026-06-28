"""Contract tests for the lazy monkeypatcher (``odoo._monkeypatches``).

The loader calls ``patch_module()`` on each patch submodule. A submodule that
forgets to define it would otherwise blow up at startup with a bare
``AttributeError`` (now a clear ``TypeError``, see
``odoo/_monkeypatches/__init__.py``) the first time its target module is
imported — far from the offending commit. These tests pin the contract at test
time instead, so a malformed patch fails the suite, not production boot.

Per-patch *behavioural* tests live alongside (e.g. ``test_mimetypes``); this is
the structural contract shared by all of them.
"""

import importlib
import pkgutil

import odoo._monkeypatches as monkeypatches
from odoo.tests.common import BaseCase


class TestMonkeypatchContract(BaseCase):
    def _patch_submodules(self):
        # Patch submodules are named after the module they patch; leading
        # underscore marks a helper (e.g. ``_excel_utils``), not a patch.
        return [
            module.name
            for module in pkgutil.iter_modules(monkeypatches.__path__)
            if not module.name.startswith("_")
        ]

    def test_submodules_discovered(self):
        # Guard against a refactor that silently relocates the patches and makes
        # the contract test below vacuously pass.
        self.assertTrue(
            self._patch_submodules(), "no monkeypatch submodules were discovered"
        )

    def test_every_patch_exposes_callable_patch_module(self):
        for name in self._patch_submodules():
            with self.subTest(patch=name):
                module = importlib.import_module(f"odoo._monkeypatches.{name}")
                self.assertTrue(
                    callable(getattr(module, "patch_module", None)),
                    f"odoo._monkeypatches.{name} must define a callable "
                    f"patch_module() (see odoo/_monkeypatches/README.md)",
                )
