"""The framework's public import surfaces declare what they export.

Addon code reaches the framework through a small set of façade modules. Each one
is API: what it re-exports is a promise, and a promise that is only implied by
"whatever happens to be bound at module level" cannot be reviewed, cannot be
diffed, and silently grows every time somebody adds an import for internal use.

``odoo.api`` / ``odoo.fields`` / ``odoo.models`` / ``odoo.libs`` / ``odoo.http``
already declared ``__all__``. ``odoo.tools`` -- the largest of them, 101 symbols
-- and ``odoo.exceptions`` -- imported by essentially every addon -- did not.
They do now, and these tests keep all of them honest.

The load-bearing case is :meth:`TestToolsSurface.test_all_matches_what_is_reexported`.
The others check that ``__all__`` is *satisfiable*; that one checks it is
*complete*, which is the direction drift actually travels: an import added to
``odoo/tools/__init__.py`` for internal convenience becomes public the moment it
lands, whether or not anyone meant it to. Same symmetry
``package_index_check.py`` applies to the package READMEs.
"""

import ast
import importlib
from pathlib import Path

from odoo.tests import BaseCase

#: Every module that is a public import surface for addon code.
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
        """An ``__all__`` entry that does not exist breaks ``import *`` at runtime."""
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
    """``odoo.tools`` is a pure re-export façade, so its ``__all__`` is checkable."""

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
        """Every re-exported name is exported, and every export is re-exported.

        The first direction stops a new import from becoming accidental API. The
        second stops ``__all__`` from outliving the import it described.
        """
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
        """``_`` is private-spelled and public: ``import *`` would skip it."""
        import odoo.tools

        self.assertIn("_", odoo.tools.__all__)


class TestExceptionsSurface(BaseCase):
    def test_all_matches_the_defined_exceptions(self):
        """``odoo.exceptions`` defines its classes locally, so the check is exact."""
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
        """These are the types the RPC layer understands; they are the contract."""
        import odoo.exceptions

        for name in ("UserError", "AccessError", "ValidationError", "MissingError"):
            with self.subTest(name=name):
                self.assertIn(name, odoo.exceptions.__all__)
