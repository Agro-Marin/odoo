"""Enable standalone (database-free) testing of addon ``tools`` leaf modules.

Pytest-only file — never imported by the Odoo module loader.

Tier-1 suites living inside an addon (e.g. ``account/tools/tests``) resolve to
dotted module names like ``addons.account.tools.tests.test_x``; importing
them would execute the addon's heavy ``__init__.py`` (models, controllers,
framework imports). This conftest sits *outside* the addon packages, so it is
imported first and can pre-register ``sys.modules`` stubs for those parents —
the leaf modules under test then import normally without the framework. Same
mechanism as :mod:`odoo._testing_bootstrap`.
"""

from pathlib import Path

from odoo._testing_bootstrap import _stub_package

_ADDONS_DIR = Path(__file__).resolve().parent

#: Addons carrying a Tier-1 ``<addon>/tools/tests`` suite. Add the addon name
#: here and its testpath to pytest.ini; nothing else is needed.
_TIER1_ADDONS = ("account", "mail")

# Test bodies import the leaf modules as ``addons.<addon>.tools.X`` (rootdir on
# sys.path via pythonpath = .).
_stub_package("addons", _ADDONS_DIR)
for _addon in _TIER1_ADDONS:
    _stub_package(f"addons.{_addon}", _ADDONS_DIR / _addon)
    _stub_package(f"addons.{_addon}.tools", _ADDONS_DIR / _addon / "tools")

    # Pytest's package collection resolves the addon ancestors relative to the
    # first ancestor without __init__.py (this directory), i.e. as top-level
    # ``<addon>`` / ``<addon>.tools`` — stub those names as well so the Package
    # nodes never execute the real __init__.py.
    _stub_package(_addon, _ADDONS_DIR / _addon)
    _stub_package(f"{_addon}.tools", _ADDONS_DIR / _addon / "tools")
