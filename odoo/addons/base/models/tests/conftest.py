"""Enable standalone (database-free) testing of the view ``NameManager``.

Registers ``sys.modules`` stubs for the ``odoo.addons.base.models`` package
chain (see :mod:`odoo._testing_bootstrap`) so the ``ir_ui_view_name_manager``
leaf module imports without booting the framework or a database.

The leaf module pulls ``_`` and ``frozendict`` from ``odoo.tools``. To avoid
executing the real ``odoo/tools/__init__.py`` (and to stay compatible with a
bare ``odoo.tools`` stub another suite may have registered in the same pytest
process), a shim provides those two names, adding them only when missing so a
real, already-imported ``odoo.tools`` is left untouched.
"""

import sys
import types
from pathlib import Path

from odoo._testing_bootstrap import stub_odoo_packages

stub_odoo_packages(__file__)


def _stub_pytest_package_chain() -> None:
    """Short-circuit pytest's ``Package`` collectors for this suite.

    pytest (>= 8) imports every ancestor directory with an ``__init__.py`` as a
    ``Package`` node. Here those are ``odoo/addons/base`` and
    ``odoo/addons/base/models``, which ``module_name_from_path`` names ``base``
    and ``base.models`` (the walk stops at ``odoo/addons``, which has no
    ``__init__.py``). Importing the real ``base/__init__.py`` under those names
    would boot every base model and be rejected by the ORM metaclass.

    ``import_path`` reuses ``sys.modules[module_name]`` when already registered,
    so pre-registering inert stubs keeps those ``__init__.py`` files from
    running. No real module is imported as top-level ``base``, so the stubs
    cannot shadow anything.
    """
    tests_dir = Path(__file__).resolve().parent
    for name, path in (
        ("base", tests_dir.parents[1]),
        ("base.models", tests_dir.parents[0]),
    ):
        if name not in sys.modules:
            module = types.ModuleType(name)
            module.__path__ = [str(path)]
            module.__package__ = name
            module.__file__ = str(path / "__init__.py")
            sys.modules[name] = module


_stub_pytest_package_chain()


def _ensure_tools_stub() -> None:
    tools = sys.modules.get("odoo.tools")
    if tools is None:
        # conftest.py is at odoo/addons/base/models/tests/: parents[4] = odoo/
        tools_path = Path(__file__).resolve().parents[4] / "tools"
        tools = types.ModuleType("odoo.tools")
        tools.__path__ = [str(tools_path)]
        tools.__package__ = "odoo.tools"
        tools.__file__ = str(tools_path / "__init__.py")
        sys.modules["odoo.tools"] = tools

    if not hasattr(tools, "frozendict"):

        class frozendict(dict):  # mirrors odoo.tools.frozendict's lowercase name
            """Minimal read-only-by-convention dict stand-in for tests."""

        tools.frozendict = frozendict

    if not hasattr(tools, "_"):

        def _(source, *args, **kwargs):
            """Translation shim: plain %-formatting, no language lookup."""
            if args:
                return source % args
            if kwargs:
                return source % kwargs
            return source

        tools._ = _


_ensure_tools_stub()
