"""Lazy module monkeypatcher

Each patch submodule is named after the module (stdlib or third-party) it
patches, and must define a `patch_module` function (enforced by `patch_module`
below and by base/tests/test_monkeypatches.py).

This function will be called either immediately if the module to patch is
already imported when the monkey patcher runs, or right after that module is
imported otherwise.

Helper modules that are not themselves patches use a leading underscore
(e.g. `_excel_utils`, used by the `xlsxwriter` patch); they are skipped by
`patch_init` and need not define `patch_module`.
"""

import importlib
import os
import pkgutil
import sys
import time
from types import ModuleType, SimpleNamespace
from typing import Any


class PatchImportHook:
    """Register hooks that are run on import."""

    def __init__(self) -> None:
        self.hooks: set[str] = set()

    def add_hook(self, fullname: str) -> None:
        """Register a hook after a module is loaded.
        If already loaded, run hook immediately."""
        self.hooks.add(fullname)
        if fullname in sys.modules:
            patch_module(fullname)

    def find_spec(
        self, fullname: str, path: Any = None, target: ModuleType | None = None
    ) -> Any:
        if fullname not in self.hooks:
            return None  # let python use another import hook to import this fullname

        # skip all finders before this one
        idx = sys.meta_path.index(self)
        for finder in sys.meta_path[idx + 1 :]:
            spec = finder.find_spec(fullname, path, target)
            if spec is not None:
                # we found a spec, change the loader

                def exec_module(
                    module: ModuleType, exec_module=spec.loader.exec_module
                ) -> None:
                    exec_module(module)
                    patch_module(module.__name__)

                spec.loader = SimpleNamespace(
                    create_module=spec.loader.create_module,
                    exec_module=exec_module,
                )
                return spec
        # No downstream finder can locate the module: return None (not raise) so
        # the import machinery produces a standard ModuleNotFoundError. Raising a
        # bare ImportError here breaks importlib.util.find_spec() (contract:
        # return None for a missing module) and `except ModuleNotFoundError`
        # probing of optional deps (e.g. num2words, stdnum).
        return None


HOOK_IMPORT = PatchImportHook()
sys.meta_path.insert(0, HOOK_IMPORT)


def patch_init() -> None:
    os.environ["TZ"] = "UTC"  # Set the timezone
    if hasattr(time, "tzset"):
        time.tzset()

    for submodule in pkgutil.iter_modules(__path__):
        # Each patch submodule is named after the module it patches. Helper
        # modules use a leading underscore (e.g. _excel_utils, used by the
        # xlsxwriter patch) and are not patch targets — skip them.
        if submodule.name.startswith("_"):
            continue
        HOOK_IMPORT.add_hook(submodule.name)


def patch_module(name: str) -> None:
    module = importlib.import_module(f".{name}", __name__)
    patch = getattr(module, "patch_module", None)
    if not callable(patch):
        # A patch submodule that imports its own target at top level (e.g.
        # ``import bs4`` in bs4.py) re-enters this hook while the submodule is
        # still initializing, before its ``patch_module()`` is defined. Skip the
        # re-entrant call instead of raising on the half-built module: at runtime
        # the target is first imported by application code (not by the patch
        # submodule), so the patch is applied through that non-re-entrant path.
        spec = getattr(module, "__spec__", None)
        if spec is not None and getattr(spec, "_initializing", False):
            return
        # Fail loud and actionable at startup rather than with a bare
        # AttributeError from deep in the import machinery: every submodule here
        # is, by contract (see README.md), a patch for the third-party/stdlib
        # module of the same name and must expose a patch_module() entry point.
        raise TypeError(
            f"odoo._monkeypatches.{name} must define a callable patch_module() "
            f"(see odoo/_monkeypatches/README.md); found {patch!r}."
        )
    patch()
