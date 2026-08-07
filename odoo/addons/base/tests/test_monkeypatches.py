import importlib
import pkgutil

import odoo._monkeypatches as monkeypatches
from odoo.tests.common import BaseCase


class TestMonkeypatchContract(BaseCase):
    def _patch_submodules(self):
        return [
            module.name
            for module in pkgutil.iter_modules(monkeypatches.__path__)
            if not module.name.startswith("_")
        ]

    def test_submodules_discovered(self):
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


class TestLoaderCapabilitiesSurvivePatching(BaseCase):
    def _hooked_and_wrapped(self):
        import sys

        from odoo._monkeypatches import _PatchingLoader

        return [
            name
            for name in monkeypatches.HOOK_IMPORT.hooks
            if isinstance(
                getattr(sys.modules.get(name), "__loader__", None), _PatchingLoader
            )
        ]

    def test_the_wrapper_is_actually_exercised(self):
        self.assertTrue(
            self._hooked_and_wrapped(),
            "no hooked module carries a _PatchingLoader; the capability "
            "assertions below would pass trivially",
        )

    def test_wrapped_loaders_delegate_their_capabilities(self):
        import sys

        for name in self._hooked_and_wrapped():
            loader = sys.modules[name].__loader__
            underlying = loader._loader
            with self.subTest(module=name):
                for capability in (
                    "get_source",
                    "get_data",
                    "get_resource_reader",
                    "is_package",
                ):
                    self.assertEqual(
                        hasattr(loader, capability),
                        hasattr(underlying, capability),
                        f"{name}: wrapper hides {capability}",
                    )

    def test_patching_is_idempotent(self):
        from odoo._monkeypatches import _APPLIED, patch_module

        applied = set(_APPLIED)
        self.assertTrue(applied, "nothing has been patched; test is vacuous")
        for name in applied:
            patch_module(name)
        self.assertEqual(applied, set(_APPLIED))
