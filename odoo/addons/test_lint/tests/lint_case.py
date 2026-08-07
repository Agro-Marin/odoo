import ast
import fnmatch
import functools
import inspect
import re
from collections.abc import Iterable
from pathlib import Path

from odoo import tools
from odoo.modules import Manifest
from odoo.modules.registry import Registry
from odoo.tests.common import BaseCase, get_db_name, no_retry

_T_CALL_ASSETS_RE = re.compile(r"""t-call-assets=\\?["']([\w.]+)\\?["']""")


def core_root() -> str:
    """The repository this fork owns: the parent of ``odoo/odoo``."""
    return str(Path(tools.config.root_path).parent)


def is_core_path(path: str) -> bool:
    """Whether *path* belongs to this repository rather than a sibling checkout.

    The addons path assembles four independently-versioned repositories
    (``odoo``, ``enterprise``, ``design-themes``, ``agromarin``), and only the
    first is this one's to change: ``enterprise`` is a pristine upstream mirror.
    A rule enforced against all four reports thousands of findings nobody here
    can act on, which is how a gate stops being read.
    """
    return path.startswith(core_root())


@functools.cache
def framework_paths() -> tuple[str, ...]:
    """Every ``.py`` of the framework itself -- the half no addon root contains.

    ``odoo/orm``, ``odoo/tools``, ``odoo/http`` and ``odoo/service`` sit beside
    ``odoo/addons``, not inside it, so a scan driven by
    :meth:`LintCase._module_roots` cannot reach them: 531 files, including
    ``odoo/tools/sql.py``, which is where hand-built SQL actually lives. Every
    AST checker here was blind to all of it.
    """
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
    """Return the filesystem paths of addon modules."""
    if modules is None:
        return [m.path for m in Manifest.all_addon_manifests()]
    return [m.path for name in modules if (m := Manifest.for_addon(name))]


@functools.cache
def module_file_paths(modules: tuple[str, ...] | None = None) -> tuple[str, ...]:
    """Every file under every addon root, walked once per process.

    Eight tests ask for the same ~18k paths and the walk alone costs a second
    each, so it is done once and shared.
    """
    return tuple(
        str(dirpath / name)
        for modroot in _module_roots(modules)
        for dirpath, _, filenames in Path(modroot).walk()
        for name in filenames
    )


def iter_module_files(*globs: str, modules=None):
    """Yield paths of all module files matching the provided globs (AND-ed).

    Globs use fnmatch semantics on full paths, so ``"*.py"`` matches any ``.py``
    file at any depth and ``"**/static/**/*.js"`` matches JS files inside
    ``static/`` subdirectories.

    Whole-tree walks are cached per module set: eight tests ask for the same
    18k paths, and the walk alone is a second each.

    A function rather than only a method, because it never needed an instance:
    ``XmlRecordLinter.setUpClass`` was constructing a ``TestCase`` -- with no
    test method and nothing to run -- purely to reach it.
    """
    for path in module_file_paths(None if modules is None else tuple(modules)):
        if all(fnmatch.fnmatch(path, glob) for glob in globs):
            yield path


def core_xml_files() -> list[str]:
    """Every XML file in the repository this fork owns.

    The one selection behind every XML gate and both fixers, so they cannot
    drift apart -- which they had, the lint test reporting 12 665 files and the
    fixer declining 9 876 of them.
    """
    return [path for path in iter_module_files("*.xml") if is_core_path(path)]


def core_module_roots() -> list[str]:
    """Addon roots belonging to this repository, for the Rust file scanners.

    ``scan_regex_patterns`` and ``scan_byte_patterns`` take roots rather than
    file lists, so a gate built on them cannot be scoped by filtering results
    after the fact without still paying to read every sibling checkout. Handing
    them the core roots is both the scope every other gate here uses and the
    cheaper walk.
    """
    return [path for path in _module_roots() if is_core_path(path)]


@no_retry
class LintCase(BaseCase):
    """Utility methods for lint-type test cases."""

    _module_roots = staticmethod(_module_roots)
    iter_module_files = staticmethod(iter_module_files)

    def assert_ratchet(self, findings, floor: int, what: str, fix: str) -> None:
        """Assert that *findings* number exactly *floor*, and say so either way.

        An exact match, in the style of ``tooling/ratchet``: the count may not
        rise, and it may not fall silently either. A gate that only checks the
        upper bound lets a fix be undone by the next change without anyone
        noticing, because the count merely returns to a number that still
        passes.

        This exists because the alternative had already been tried here and
        failed. Several of these checks were red by thousands on a clean
        checkout, and the response was to downgrade them to ``_logger.warning``
        -- at which point they enforce nothing at all, and one of them ended up
        pointing at a ``_BATCH_FAIL_MODULES`` constant nobody ever wrote.
        Freezing the debt keeps the gate green, so the only thing in it is
        tomorrow's regression.
        """
        found = list(findings)
        if len(found) > floor:
            self.fail(
                f"{len(found)} {what}, floor is {floor}. {fix}\n"
                + "\n".join(f"  {item}" for item in sorted(map(str, found))[:200])
                + (f"\n  ... and {len(found) - 200} more" if len(found) > 200 else "")
            )
        if len(found) < floor:
            self.fail(
                f"{len(found)} {what} but the committed floor is {floor}. The "
                f"debt went down -- lower the floor to {len(found)} in this same "
                f"change, so it cannot come back unnoticed."
            )

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
