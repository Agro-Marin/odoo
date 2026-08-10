import ast
import fnmatch
import functools
import inspect
import os
import re
from collections.abc import Iterable
from pathlib import Path

from odoo import tools
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


@no_retry
class LintCase(BaseCase):
    _module_roots = staticmethod(_module_roots)
    iter_module_files = staticmethod(iter_module_files)

    def assert_ratchet(
        self, findings, floor: int, what: str, fix: str, *, exact: bool = True
    ) -> None:
        found = list(findings)
        if len(found) > floor:
            self.fail(
                f"{len(found)} {what}, floor is {floor}. {fix}\n"
                + "\n".join(f"  {item}" for item in sorted(map(str, found))[:200])
                + (f"\n  ... and {len(found) - 200} more" if len(found) > 200 else "")
            )
        if exact and len(found) < floor:
            self.fail(
                f"{len(found)} {what} but the committed floor is {floor}. The "
                f"debt went down -- lower the floor to {len(found)} in this same "
                f"change, so it cannot come back unnoticed."
            )

    @staticmethod
    def served_bundle_names(env) -> list[str]:
        installed = set(
            env["ir.module.module"].search([("state", "=", "installed")]).mapped("name")
        )
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
        return sorted(
            name for name in (names - included) | (names & linked) if "." in name
        )


def iter_registry_methods(registry=None):
    if registry is None:
        registry = Registry(get_db_name())
    for model_name, model_cls in registry.items():
        for method_name, _ in inspect.getmembers(model_cls, inspect.isroutine):
            if method_name.startswith("__"):
                continue
            for parent_class in reversed(model_cls.mro()[1:-1]):
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
