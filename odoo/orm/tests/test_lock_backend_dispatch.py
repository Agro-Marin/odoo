"""Regression: row-lock methods must honor the persistence-backend seam.

``lock_for_update`` / ``try_lock_for_update`` built ``FOR UPDATE`` SQL and called
``env.execute_query`` with no ``env.backend`` branch, unlike the nine other
persistence sites. Against the in-memory backend that raised
``InMemorySqlNotSupported``. They now dispatch to ``InMemoryBackend``, where a row
locks iff it exists (no concurrent lockers). Tier-2 suite: real ``import odoo``,
no database.
"""

import sys

import pytest

from odoo import fields, models
from odoo.exceptions import LockError
from odoo.orm.model_test_env import model_test_env

_MOD = "test_lock_backend_dispatch"


class LockThing(models.Model):
    _name = "lock.thing"
    _module = _MOD
    _description = "row-lock model"

    name = fields.Char()


def test_lock_for_update_dispatches_to_backend():
    with model_test_env(LockThing) as env:
        recs = env["lock.thing"].create({"name": "a"}) + env["lock.thing"].create(
            {"name": "b"}
        )
        recs.lock_for_update()  # was InMemorySqlNotSupported
        recs.lock_for_update(allow_referencing=True)


def test_lock_for_update_raises_on_missing_row():
    with model_test_env(LockThing) as env:
        with pytest.raises(LockError):
            env["lock.thing"].browse(999_999).lock_for_update()


def test_try_lock_for_update_returns_lockable_rows_in_order():
    with model_test_env(LockThing) as env:
        a = env["lock.thing"].create({"name": "a"})
        b = env["lock.thing"].create({"name": "b"})
        recs = a + b
        assert recs.try_lock_for_update()._ids == recs._ids
        assert recs.try_lock_for_update(limit=1)._ids == (a.id,)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
