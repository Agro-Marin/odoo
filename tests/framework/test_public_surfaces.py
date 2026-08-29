import ast
import importlib
import unittest
from pathlib import Path

SURFACES = (
    "odoo.api",
    "odoo.exceptions",
    "odoo.fields",
    "odoo.http",
    "odoo.libs",
    "odoo.models",
    "odoo.tools",
)


class TestPublicSurfaces(unittest.TestCase):
    def test_every_surface_declares_all(self):
        for name in SURFACES:
            with self.subTest(module=name):
                module = importlib.import_module(name)
                self.assertTrue(
                    hasattr(module, "__all__"),
                    f"{name} is a public import surface and must declare __all__",
                )

    def test_every_exported_name_resolves(self):
        for name in SURFACES:
            module = importlib.import_module(name)
            missing = [n for n in module.__all__ if not hasattr(module, n)]
            with self.subTest(module=name):
                self.assertEqual(
                    missing, [], f"{name}.__all__ names missing attributes"
                )

    def test_no_duplicate_exports(self):
        for name in SURFACES:
            module = importlib.import_module(name)
            dupes = sorted({n for n in module.__all__ if module.__all__.count(n) > 1})
            with self.subTest(module=name):
                self.assertEqual(dupes, [], f"{name}.__all__ has duplicates")


class TestToolsSurface(unittest.TestCase):
    @staticmethod
    def _reexported_names() -> set[str]:
        source = Path(importlib.import_module("odoo.tools").__file__).read_text(
            encoding="utf-8"
        )
        names: set[str] = set()
        for node in ast.parse(source).body:
            if isinstance(node, ast.ImportFrom):
                names |= {alias.asname or alias.name for alias in node.names}
        return names

    def test_all_matches_what_is_reexported(self):
        import odoo.tools

        declared = set(odoo.tools.__all__)
        reexported = self._reexported_names()
        self.assertEqual(
            sorted(reexported - declared),
            [],
            "imported into odoo/tools/__init__.py but absent from __all__ — either "
            "export it deliberately or import it under a private alias",
        )
        self.assertEqual(
            sorted(declared - reexported),
            [],
            "listed in odoo.tools.__all__ but no longer imported there",
        )

    def test_gettext_helper_is_exported(self):
        import odoo.tools

        self.assertIn("_", odoo.tools.__all__)


class TestExceptionsSurface(unittest.TestCase):
    def test_all_matches_the_defined_exceptions(self):
        import odoo.exceptions

        source = Path(odoo.exceptions.__file__).read_text(encoding="utf-8")
        defined = {
            node.name
            for node in ast.parse(source).body
            if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
        }
        self.assertEqual(
            defined,
            set(odoo.exceptions.__all__),
            "odoo.exceptions.__all__ has drifted from the exceptions it defines",
        )

    def test_the_rpc_layer_exceptions_are_public(self):
        import odoo.exceptions

        for name in ("UserError", "AccessError", "ValidationError", "MissingError"):
            with self.subTest(name=name):
                self.assertIn(name, odoo.exceptions.__all__)


class TestToolsSubmoduleSurfaces(unittest.TestCase):
    """The tools shims declare what they publish, the way odoo.tools does.

    `odoo.tools.image` declared one name while addons imported nine from it,
    including `ImageProcess` and `base64_to_image`; `mail`, `misc` and `json`
    had the same shape.  A shim whose `__all__` omits its own re-exports breaks
    `import *`, and makes every re-export look unused to a linter.

    The rule: a shim publishes what it defines, plus what it takes from another
    odoo module (absolute or relative).  A third-party import -- PIL, babel --
    is incidental, and an odoo import meant to stay private takes a `_` alias,
    which is what `odoo.tools.__init__`'s own gate advises.
    """

    SHIMS = ("image", "json", "mail", "misc")

    @staticmethod
    def _surface(module_name: str) -> tuple[set[str], set[str]]:
        module = importlib.import_module(f"odoo.tools.{module_name}")
        source = Path(module.__file__).read_text(encoding="utf-8")
        names: set[str] = set()
        for node in ast.parse(source).body:
            if isinstance(node, ast.ImportFrom):
                if node.level > 0 or (node.module or "").startswith("odoo"):
                    names |= {alias.asname or alias.name for alias in node.names}
            elif isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                names |= {
                    t.id
                    for t in node.targets
                    if isinstance(t, ast.Name) and t.id != "__all__"
                }
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
        public = {n for n in names if not n.startswith("_")}
        return set(module.__all__), public

    def test_every_shim_declares_all(self):
        for name in self.SHIMS:
            with self.subTest(module=name):
                module = importlib.import_module(f"odoo.tools.{name}")
                self.assertTrue(
                    hasattr(module, "__all__"), f"{name} must declare __all__"
                )

    def test_all_matches_what_the_shim_publishes(self):
        for name in self.SHIMS:
            declared, public = self._surface(name)
            with self.subTest(module=name):
                self.assertEqual(
                    sorted(public - declared),
                    [],
                    f"odoo.tools.{name} publishes these but omits them from __all__ — "
                    "export them, or give the import a private `_` alias",
                )
                self.assertEqual(
                    sorted(declared - public),
                    [],
                    f"odoo.tools.{name}.__all__ names something it no longer publishes",
                )

    def test_every_exported_name_resolves(self):
        for name in self.SHIMS:
            module = importlib.import_module(f"odoo.tools.{name}")
            missing = [n for n in module.__all__ if not hasattr(module, n)]
            with self.subTest(module=name):
                self.assertEqual(
                    missing, [], f"odoo.tools.{name}.__all__ has dead names"
                )
