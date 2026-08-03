import ast
import fnmatch
import inspect
import re
from collections.abc import Iterable
from pathlib import Path

from odoo.modules import Manifest
from odoo.modules.registry import Registry
from odoo.tests.common import BaseCase, get_db_name, no_retry

#: `t-call-assets="<bundle>"`, as it survives into `ir_ui_view.arch_db`.
_T_CALL_ASSETS_RE = re.compile(r"""t-call-assets=\\?["']([\w.]+)\\?["']""")


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

    @staticmethod
    def served_bundle_names(env) -> list[str]:
        """Bundle names that reach a browser, for the installed modules.

        Two ways to be served, and a bundle needs only one of them: no other
        bundle includes it, or a template links it with ``t-call-assets``.

        The second half is not a refinement. Being included somewhere does not
        make a bundle a fragment: ``web.assets_web`` is included by
        ``web.assets_web_dark`` and ``point_of_sale.assets_prod`` by
        ``point_of_sale.assets_prod_dark``, and both are linked by a template in
        their own right. Reading inclusion alone as the test left the PoS UI --
        386 unresolvable palette tokens across 1266 declarations -- outside
        every check built on this list, while reporting its dark sibling.

        Asking the templates rather than the names, because the ``_`` prefix
        that marks ``web._assets_core`` as a fragment is a convention several
        real fragments do not follow (``mail.assets_core_common``,
        ``portal.assets_chatter_helpers``), and a fragment counted as served
        reports offences its consumers already answer with a ``remove``.
        """
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
