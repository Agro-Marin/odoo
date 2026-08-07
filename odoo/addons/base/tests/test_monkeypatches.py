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
    """Hooking a module must not cost it its loader's other capabilities.

    ``find_spec`` wraps the real loader so the patch runs after ``exec_module``.
    It used to *replace* it with a ``SimpleNamespace`` carrying only
    ``create_module``/``exec_module``, which silently dropped ``get_source``
    (``inspect``), ``get_data`` (``pkgutil``) and ``get_resource_reader``
    (``importlib.resources``) for every module that actually went through the
    hook — the six not already imported when ``patch_init()`` runs.

    The symptom was quiet: ``pkgutil.get_data`` returned ``None`` rather than
    raising, and ``inspect.getsource`` kept working (it falls back to
    ``__spec__.origin``), so nothing pointed at the loader.
    """

    def _hooked_and_wrapped(self):
        """Patch submodules whose target went through the import hook."""
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
        """Guard the guard: if nothing is wrapped, the test below is vacuous."""
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
        """Re-applying must not wrap the wrapper.

        Every patch here rebinds a name to a wrapper over whatever it held at
        call time, so a second application nests. Measured on werkzeug's
        ``MultiDict.deepcopy`` before the guard: depth 1, 2, 3, 4 on repeated
        calls — behaviour intact, one extra frame each time, permanently.
        """
        from odoo._monkeypatches import _APPLIED, patch_module

        applied = set(_APPLIED)
        self.assertTrue(applied, "nothing has been patched; test is vacuous")
        for name in applied:
            patch_module(name)  # must be a no-op
        self.assertEqual(applied, set(_APPLIED))
