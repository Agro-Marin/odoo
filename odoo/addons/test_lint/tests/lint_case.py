import ast
import fnmatch
import inspect
from collections.abc import Iterable
from pathlib import Path

from odoo.modules import Manifest
from odoo.modules.registry import Registry
from odoo.tests.common import BaseCase, get_db_name, no_retry


def get_odoo_module_name(python_module_name: str) -> str:
    if python_module_name.startswith("odoo.addons."):
        return python_module_name.split(".")[2]
    if python_module_name == "odoo.models":
        return "odoo"
    return python_module_name


@no_retry
class LintCase(BaseCase):
    @staticmethod
    def _module_roots(modules=None) -> list[str]:
        if modules is None:
            return [m.path for m in Manifest.all_addon_manifests()]
        return [m.path for name in modules if (m := Manifest.for_addon(name))]

    def iter_module_files(self, *globs: str, modules=None):
        for modroot in self._module_roots(modules):
            for dirpath, _, filenames in Path(modroot).walk():
                fnames = [str(dirpath / n) for n in filenames]
                for glob in globs:
                    fnames = fnmatch.filter(fnames, glob)
                yield from fnames


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
