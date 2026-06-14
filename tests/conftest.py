"""Session-scoped fixtures for the database-free model unit tests.

Provides the ``base_registry`` fixture that ``tests/models/conftest.py``'s
``env`` fixture depends on. It was referenced but never defined, so the entire
``tests/models/`` pytest suite errored at collection with
``fixture 'base_registry' not found``.

``ModelRegistry._build`` auto-discovers *all* model definitions from the same
module as any provided class, so seeding it with a single ``base`` model pulls
in the whole base addon (res.partner, res.currency, ir.sequence, …) — exactly
the models the unit tests exercise. The registry is built once per session and
shared; each test still gets a fresh in-memory cursor + storage via
``model_test_env(registry=base_registry)``.
"""

import pytest


@pytest.fixture(scope="session")
def base_registry():
    """Build an in-memory registry of every ``base`` module model, once."""
    # Import the base models package so MetaModel's per-module collector is
    # fully populated before ModelRegistry auto-discovers from it.
    import odoo.addons.base.models  # noqa: F401 — import for registration side effect
    from odoo.addons.base.models.ir_attachment import IrAttachment
    from odoo.orm.testing import ModelRegistry

    return ModelRegistry([IrAttachment])
