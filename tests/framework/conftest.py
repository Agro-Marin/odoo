"""Tier-2 real-import suites for the framework's own surfaces.

No stubs are registered here, deliberately. These tests assert things about the
REAL `odoo.*` packages -- that every public facade declares `__all__` and that
every monkeypatch is applied whatever the import order -- so the Tier-1
`sys.modules` stubs (`odoo/_testing_bootstrap.py`) would replace exactly the
objects under test. That is why this directory sits outside `pytest.ini`'s
`testpaths` and runs in the same invocation as `odoo/orm/tests`,
`odoo/http/tests` and `tests/service`.

Nothing in here touches a database.
"""

# The patches are applied by `odoo.init` as an import side effect, and nothing
# in this suite would otherwise pull it in: `import odoo._monkeypatches` gives
# you the hooks, not the patched libraries. Under `odoo-bin` that happens long
# before any test runs, which is why the suite passed there and fails here
# without this line.
import odoo.init  # noqa: F401  imported for the bootstrap side effect
