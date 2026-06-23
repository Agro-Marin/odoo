"""Shared bootstrap for the standalone (database-free) pytest suites.

The component (:mod:`odoo.orm.components`) and ``_field_access`` layers are
designed to have **zero** Odoo dependencies, so their unit tests can run
without spinning up the framework or a database.  But the test bodies use
absolute imports like ``from odoo.orm.components.cache import FieldCache``,
and Python resolves those by walking the package chain and executing each
``__init__.py`` — including ``odoo/orm/__init__.py`` (``import odoo.init``),
which pulls in the whole framework (monkeypatches, werkzeug, the HTTP stack)
and triggers circular imports.

To avoid that, each standalone suite's ``conftest.py`` calls
:func:`stub_odoo_packages` once, which pre-registers minimal package *stubs*
in ``sys.modules`` for the ``odoo.*`` parents of the suite.  Each stub has a
correct ``__path__`` pointing at the real source directory, so leaf modules
(``cache.py``, ``_fallback.py``, …) still import normally — but the heavy
``__init__.py`` files never run.

``odoo`` itself is a PEP 420 namespace package (no ``__init__.py``), so it is
free to import; the stub for it only exists to give the child stubs a
registered parent.

This is the single source of truth for the stub logic, replacing the
copy-pasted ``_stub_package`` helper that previously lived in every suite's
``conftest.py``.
"""

import sys
import types
from pathlib import Path

__all__ = ["stub_odoo_packages"]


def _stub_package(name: str, path: Path) -> None:
    """Register a minimal package stub in ``sys.modules`` (no-op if present)."""
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    module.__package__ = name
    module.__file__ = str(path / "__init__.py")
    sys.modules[name] = module


def stub_odoo_packages(conftest_file: str) -> None:
    """Stub every ``odoo.*`` package between the ``odoo`` root and the suite.

    Pass the calling ``conftest.py``'s ``__file__``.  Its parent is the suite's
    ``tests/`` directory; this walks upward to the ``odoo`` package root,
    registering a stub for ``odoo`` and for each intermediate package so the
    suite's absolute ``from odoo.… import …`` imports resolve straight to the
    leaf modules without executing any real ``__init__.py``.

    Example — ``odoo/orm/components/tests/conftest.py`` registers stubs for
    ``odoo``, ``odoo.orm`` and ``odoo.orm.components``.
    """
    tests_dir = Path(conftest_file).resolve().parent

    # Collect the package directories between the tests/ dir and the odoo root.
    intermediates: list[Path] = []
    current = tests_dir.parent
    while current.name and current.name != "odoo":
        intermediates.append(current)
        current = current.parent

    if current.name != "odoo":
        raise RuntimeError(
            f"could not locate the 'odoo' package root above {conftest_file!r}"
        )

    # Register parents first: odoo, then each child down to the suite's package.
    _stub_package("odoo", current)
    name = "odoo"
    for package_dir in reversed(intermediates):
        name = f"{name}.{package_dir.name}"
        _stub_package(name, package_dir)
