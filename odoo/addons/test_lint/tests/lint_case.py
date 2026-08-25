import ast
import contextlib
import fnmatch
import functools
import inspect
import os
import re
from collections.abc import Iterable
from pathlib import Path

from odoo import SUPERUSER_ID, api, tools
from odoo.modules import Manifest
from odoo.modules.registry import Registry
from odoo.tests.common import BaseCase, get_db_name, no_retry

_T_CALL_ASSETS_RE = re.compile(r"""t-call-assets=\\?["']([\w.]+)\\?["']""")


def core_root() -> str:
    return str(Path(tools.config.root_path).parent)


def is_core_path(path: str) -> bool:
    root = core_root()
    return path == root or path.startswith(root + os.sep)


@functools.cache
def framework_paths() -> tuple[str, ...]:
    root = Path(tools.config.root_path)
    addons = root / "addons"
    return tuple(
        str(path)
        for path in sorted(root.rglob("*.py"))
        if addons not in path.parents and "__pycache__" not in path.parts
    )


def get_odoo_module_name(python_module_name: str) -> str:
    if python_module_name.startswith("odoo.addons."):
        return python_module_name.split(".")[2]
    if python_module_name == "odoo.models":
        return "odoo"
    return python_module_name


def _module_roots(modules: tuple[str, ...] | None = None) -> list[str]:
    if modules is None:
        return [m.path for m in Manifest.all_addon_manifests()]
    return [m.path for name in modules if (m := Manifest.for_addon(name))]


@functools.cache
def module_file_paths(modules: tuple[str, ...] | None = None) -> tuple[str, ...]:
    return tuple(
        str(dirpath / name)
        for modroot in _module_roots(modules)
        for dirpath, _, filenames in Path(modroot).walk()
        for name in filenames
    )


def iter_module_files(*globs: str, modules=None):
    for path in module_file_paths(None if modules is None else tuple(modules)):
        if all(fnmatch.fnmatch(path, glob) for glob in globs):
            yield path


def core_xml_files() -> list[str]:
    return [path for path in iter_module_files("*.xml") if is_core_path(path)]


@functools.cache
def core_module_names() -> frozenset[str]:
    return frozenset(
        manifest.name
        for manifest in Manifest.all_addon_manifests()
        if is_core_path(str(manifest.path))
    )


@functools.cache
def _core_data_files() -> tuple[Path, ...]:
    from . import _pretty_xml

    return tuple(
        path for path in map(Path, core_xml_files()) if _pretty_xml.is_formattable(path)
    )


def core_data_files() -> list[Path]:
    return list(_core_data_files())


def core_module_roots() -> list[str]:
    return [path for path in _module_roots() if is_core_path(path)]


@functools.cache
def _ratchet():
    """`tooling/ratchet/ratchet.py`, loaded off the checkout beside us.

    Imported by path rather than by name: `tooling/` is not a package on
    `sys.path` under `odoo-bin`, and putting it there for one import would put
    every other tooling module there too.
    """
    import importlib.util
    import sys

    name = "_test_lint_ratchet"
    path = Path(core_root()) / "tooling" / "ratchet" / "ratchet.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - unreachable in-tree
        raise RuntimeError(f"cannot load the ratchet from {path}")
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: `ratchet.py` carries `from __future__ import
    # annotations` and a dataclass whose field annotations name the class itself,
    # and `dataclasses` resolves those through `sys.modules[cls.__module__]`.
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module


def baseline_floor(gate: str) -> int:
    """The committed floor for `gate`, or 0 when no baseline names it.

    Absence means zero on purpose. A gate nobody has had to grant debt to is a
    gate at zero, and promoting one costs an explicit
    `ratchet.py <gate> --count N --update --note '…'`, which shows up in review.
    `ratchet.py --list` is then the whole of this module's debt, in one place.
    """
    baseline = _ratchet().Baseline.load(gate)
    return baseline.count if baseline else 0


@no_retry
class LintCase(BaseCase):
    _module_roots = staticmethod(_module_roots)
    iter_module_files = staticmethod(iter_module_files)

    def assert_ratchet(
        self, findings, gate: str, what: str, fix: str, *, exact: bool = True
    ) -> None:
        """Hold `findings` at the floor committed for `gate`.

        `gate` is a ratchet baseline name, never a number. A floor written into
        Python is a number that drifts silently against a tree nobody
        re-measures, and this module spent twenty-four of its last forty commits
        proving it: they changed nothing here but an integer and the comment
        above it.
        """
        if not isinstance(gate, str):
            raise TypeError(
                f"assert_ratchet takes a ratchet gate name, not {gate!r}. A floor "
                f"belongs in tooling/ratchet/baselines/, where `ratchet.py --list` "
                f"can see it and `--update --note` can move it."
            )
        floor = baseline_floor(gate)
        found = list(findings)
        if len(found) > floor:
            self.fail(
                f"{len(found)} {what}, floor is {floor} ({gate}). {fix}\n"
                + "\n".join(f"  {item}" for item in sorted(map(str, found))[:200])
                + (f"\n  ... and {len(found) - 200} more" if len(found) > 200 else "")
            )
        if exact and len(found) < floor:
            self.fail(
                f"{len(found)} {what} but the committed floor is {floor}. The debt "
                f"went down -- bank it in this same change:\n"
                f"    python tooling/ratchet/ratchet.py {gate} --count {len(found)} "
                f"--update --note '<what moved and why>'"
            )

    @staticmethod
    def served_bundle_names(env) -> list[str]:
        installed = frozenset(
            env["ir.module.module"].search([("state", "=", "installed")]).mapped("name")
        )
        return list(_served_bundle_names(installed, env))

    @staticmethod
    @contextlib.contextmanager
    def superuser_env():
        """A short-lived superuser environment on its own cursor.

        Six modules spelled this out by hand. `LintCase` is a `BaseCase`, so
        there is no `self.env` to borrow and each gate opens its own.
        """
        with Registry(get_db_name()).cursor() as cr:
            yield api.Environment(cr, SUPERUSER_ID, {})


def _served_bundle_names(installed: frozenset[str], env) -> tuple[str, ...]:
    cached = _SERVED_BUNDLES.get(installed)
    if cached is None:
        cached = _SERVED_BUNDLES[installed] = _compute_served_bundle_names(
            installed, env
        )
    return cached


#: Keyed on the installed set, which is what the answer depends on. Five gates
#: call this and it re-walks every manifest and re-runs a raw SELECT over
#: `ir_ui_view` each time.
_SERVED_BUNDLES: dict[frozenset[str], tuple[str, ...]] = {}


def _compute_served_bundle_names(installed: frozenset[str], env) -> tuple[str, ...]:
    names = set()
    included = set()
    for manifest in Manifest.all_addon_manifests():
        if manifest.name not in installed:
            continue
        assets = manifest.get("assets") or {}
        names.update(assets)
        for entries in assets.values():
            for entry in entries:
                if (
                    isinstance(entry, (list, tuple))
                    and len(entry) > 1
                    and entry[0] == "include"
                ):
                    included.add(entry[1])

    env.cr.execute("SELECT arch_db::text FROM ir_ui_view WHERE arch_db IS NOT NULL")
    linked = {
        name
        for (arch,) in env.cr.fetchall()
        for name in _T_CALL_ASSETS_RE.findall(arch)
    }
    return tuple(
        sorted(name for name in (names - included) | (names & linked) if "." in name)
    )


def iter_registry_methods(registry=None):
    if registry is None:
        registry = Registry(get_db_name())
    for model_name, model_cls in registry.items():
        for method_name, _ in inspect.getmembers(model_cls, inspect.isroutine):
            if method_name.startswith("__"):
                continue
            # The class that DEFINES the method, most-derived first. Walking
            # from the base end and stopping at the first class `getattr`
            # answers on finds the most basic class that *has* the name, which
            # for an overridden method is the one it overrides: the override is
            # then keyed under its base and, once that pair is seen, never
            # looked at again. `vars()` asks who declares it rather than who
            # answers for it.
            for parent_class in model_cls.mro()[1:-1]:
                if method_name not in vars(parent_class):
                    continue
                method = getattr(parent_class, method_name, None)
                if callable(method):
                    break
            else:
                continue
            yield model_name, model_cls, method_name, method, parent_class


class NodeVisitor[T]:
    def visit(self, node: ast.AST) -> Iterable[T]:
        visitor = getattr(self, f"visit_{node.__class__.__name__}", self.generic_visit)
        return visitor(node)

    def generic_visit(self, node: ast.AST) -> Iterable[T]:
        for child in ast.iter_child_nodes(node):
            yield from self.visit(child)
