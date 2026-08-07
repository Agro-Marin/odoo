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


class _PatchingLoader:
    """Wrap a loader so the module is patched after exec, keeping the rest.

    Delegates every attribute it does not define, because a loader is more than
    ``create_module``/``exec_module``: ``get_source`` backs ``inspect.getsource``
    for non-file loaders, ``get_data`` backs :func:`pkgutil.get_data`, and
    ``get_resource_reader`` backs :mod:`importlib.resources`.

    This replaced a ``SimpleNamespace`` carrying only the two exec hooks, which
    dropped the others silently. Measured against the unhooked control
    ``psycopg``, on hooked packages that actually went through ``find_spec``::

        pkgutil.get_data("docutils", "writers/html4css1/html4css1.css")
            -> None          (not an error -- a caller reading a resource got
                              nothing back and had to notice on its own)
        importlib.resources.files("docutils").joinpath(...).read_text()
            -> FileNotFoundError: Can't open orphan path

    Note that ``inspect.getsource`` kept working throughout: it falls back to
    ``__spec__.origin``, which is why this went unnoticed.
    """

    def __init__(self, loader: Any) -> None:
        self._loader = loader

    def create_module(self, spec: Any) -> ModuleType | None:
        return self._loader.create_module(spec)

    def exec_module(self, module: ModuleType) -> None:
        self._loader.exec_module(module)
        patch_module(module.__name__)

    def __getattr__(self, name: str) -> Any:
        # Only reached for names not defined above, so the two exec hooks stay
        # ours and everything else is the real loader's.
        return getattr(self._loader, name)

    def __repr__(self) -> str:
        return f"<_PatchingLoader wrapping {self._loader!r}>"


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
            return None

        # Not sys.meta_path.index(self): that raises ValueError out of an
        # import if this hook has been removed (a test resetting meta_path, a
        # tool rebuilding it), turning "no patch" into "no imports at all".
        # Skipping past ourselves by identity degrades to scanning the whole
        # list, which is the same answer minus the crash.
        finders = sys.meta_path
        try:
            start = finders.index(self) + 1
        except ValueError:
            start = 0
        for finder in finders[start:]:
            if finder is self:
                continue
            spec = finder.find_spec(fullname, path, target)
            if spec is not None:
                if spec.loader is not None:
                    spec.loader = _PatchingLoader(spec.loader)
                return spec
        return None


HOOK_IMPORT = PatchImportHook()
sys.meta_path.insert(0, HOOK_IMPORT)


def patch_init() -> None:
    os.environ["TZ"] = "UTC"
    if hasattr(time, "tzset"):
        time.tzset()

    for submodule in pkgutil.iter_modules(__path__):
        if submodule.name.startswith("_"):
            continue
        HOOK_IMPORT.add_hook(submodule.name)


#: Patches already applied in this process, so a second call is a no-op.
#:
#: Most patches here rebind a name to a wrapper built over whatever that name
#: held at call time, so applying one twice wraps the wrapper. Measured on
#: ``werkzeug``'s ``MultiDict.deepcopy``: nesting depth went 1, 2, 3, 4 with
#: repeated calls. Behaviour survives (each layer just delegates) but every
#: layer is a permanent extra frame on a hot path, and ``patch_module`` is
#: reachable more than once per module — ``add_hook`` calls it for an
#: already-imported module, and ``importlib.reload`` re-runs ``exec_module``.
_APPLIED: set[str] = set()


def patch_module(name: str) -> None:
    if name in _APPLIED:
        return
    module = importlib.import_module(f".{name}", __name__)
    patch = getattr(module, "patch_module", None)
    if not callable(patch):
        spec = getattr(module, "__spec__", None)
        if spec is not None and getattr(spec, "_initializing", False):
            # Circular import: the patch module is still executing, so its
            # patch_module() is not bound yet. Do NOT mark it applied — the
            # import that is in flight will come back through here.
            return
        raise TypeError(
            f"odoo._monkeypatches.{name} must define a callable patch_module() "
            f"(see odoo/_monkeypatches/README.md); found {patch!r}."
        )
    patch()
    _APPLIED.add(name)
