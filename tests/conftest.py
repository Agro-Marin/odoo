"""Session-scoped fixtures for the database-free model unit tests.

Provides ``base_registry``, which ``tests/models/conftest.py``'s ``env``
fixture builds on. ``ModelRegistry`` auto-discovers every model in the same
module as any seed class, so one ``base`` model pulls in the whole base addon
(res.partner, res.currency, …). Built once per session; each test still gets a
fresh in-memory cursor + storage via ``model_test_env``.
"""

import pytest


@pytest.fixture(scope="session")
def base_registry():
    """Build an in-memory registry of every ``base`` module model, once."""
    # Import the base models package so MetaModel's per-module collector is
    # fully populated before ModelRegistry auto-discovers from it.
    from odoo.orm.model_test_env import ModelRegistry

    import odoo.addons.base.models  # noqa: F401 — import for registration side effect
    from odoo.addons.base.models.ir_attachment import IrAttachment

    return ModelRegistry([IrAttachment])
