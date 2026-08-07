import ast
import importlib
from pathlib import Path

from odoo.tests import BaseCase

SURFACES = (
    "odoo.api",
    "odoo.exceptions",
    "odoo.fields",
    "odoo.http",
    "odoo.libs",
    "odoo.models",
    "odoo.tools",
)


class TestPublicSurfaces(BaseCase):
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


class TestToolsSurface(BaseCase):
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


class TestExceptionsSurface(BaseCase):
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
