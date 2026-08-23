import importlib
import os
import pkgutil
import sys
import time
from types import ModuleType
from typing import Any

_SELF_PREFIX = __name__ + "."


class _PatchingLoader:
    """Wrap a loader so `patch_module(target)` runs the moment exec finishes.

    `target` is the name of the *patched* module, which is not always the name
    of the module being loaded: this loader also wraps our own
    `odoo._monkeypatches.<target>` submodules, so that importing a patch
    submodule directly still applies its patch.  See `find_spec`.
    """

    def __init__(self, loader: Any, target: str) -> None:
        self._loader = loader
        self._target = target

    def create_module(self, spec: Any) -> ModuleType | None:
        return self._loader.create_module(spec)

    def exec_module(self, module: ModuleType) -> None:
        self._loader.exec_module(module)
        patch_module(self._target)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._loader, name)

    def __repr__(self) -> str:
        return f"<_PatchingLoader for {self._target!r} wrapping {self._loader!r}>"


class PatchImportHook:
    def __init__(self) -> None:
        self.hooks: set[str] = set()

    def add_hook(self, fullname: str) -> None:
        self.hooks.add(fullname)
        if fullname in sys.modules:
            patch_module(fullname)

    def _target_of(self, fullname: str) -> str | None:
        """The patched module `fullname`'s import should trigger, if any.

        Two names map to the same target: the patched module itself, and the
        `odoo._monkeypatches.<target>` submodule holding its patch.  Wrapping
        the latter is what makes the patch survive being imported before its
        target -- the submodule's own top-level `import <target>` re-enters
        `patch_module` while the submodule is still initializing and its
        `patch_module()` does not exist yet, so that call can only defer.
        """
        if fullname in self.hooks:
            return fullname
        if fullname.startswith(_SELF_PREFIX):
            target = fullname[len(_SELF_PREFIX) :]
            if target in self.hooks:
                return target
        return None

    def find_spec(
        self, fullname: str, path: Any = None, target: ModuleType | None = None
    ) -> Any:
        patched = self._target_of(fullname)
        if patched is None:
            return None

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
                    spec.loader = _PatchingLoader(spec.loader, patched)
                return spec
        return None


HOOK_IMPORT = PatchImportHook()
sys.meta_path.insert(0, HOOK_IMPORT)


def _select_run_mode() -> None:
    """Consume the `evented` pseudo-argument the prefork server re-execs with.

    `service/_prefork.py` starts the long-polling worker as
    `[sys.executable, sys.argv[0], "evented", ...]`, and `odoo.evented` has to
    be settled before `odoo.cli` parses argv -- which is why this is bootstrap
    and not a module patch.  It patches no third-party module, so it is called
    from here rather than discovered: a file named for a module it does not
    touch is how this used to hide.
    """
    import odoo

    if odoo.evented or not (len(sys.argv) > 1 and sys.argv[1] == "evented"):
        return
    sys.argv.remove("evented")
    odoo.evented = True


def patch_init() -> None:
    os.environ["TZ"] = "UTC"
    if hasattr(time, "tzset"):
        time.tzset()
    _select_run_mode()

    for submodule in pkgutil.iter_modules(__path__):
        if submodule.name.startswith("_"):
            continue
        HOOK_IMPORT.add_hook(submodule.name)


_APPLIED: set[str] = set()


def patch_module(name: str) -> None:
    """Apply `odoo._monkeypatches.<name>` to the module it patches, once.

    Not locked, deliberately.  This runs inside `exec_module`, under the import
    system's per-module lock; a lock of our own would be acquired in the
    opposite order by a thread importing a patch submodule directly, and the
    two would deadlock against each other.
    """
    if name in _APPLIED:
        return
    module = importlib.import_module(f".{name}", __name__)
    if name in _APPLIED:
        # `import_module` completed the submodule, whose own _PatchingLoader
        # already applied the patch on the way out.
        return
    patch = getattr(module, "patch_module", None)
    if not callable(patch):
        spec = getattr(module, "__spec__", None)
        if spec is not None and getattr(spec, "_initializing", False):
            # Re-entered from the submodule's top-level `import <name>`, before
            # its `patch_module()` is defined.  Deferred, not dropped: the
            # submodule's own _PatchingLoader calls us again once exec ends.
            return
        raise TypeError(
            f"odoo._monkeypatches.{name} must define a callable patch_module() "
            f"(see odoo/_monkeypatches/README.md); found {patch!r}."
        )
    patch()
    _APPLIED.add(name)


def applied() -> frozenset[str]:
    """The patches that have run.  A hooked name absent from this is deferred."""
    return frozenset(_APPLIED)
