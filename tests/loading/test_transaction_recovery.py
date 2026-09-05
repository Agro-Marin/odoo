"""Retry a commit rejection with a real registry, cache and compute queue."""

from psycopg import errors

from odoo import api
from odoo.db import db_connect
from odoo.orm.runtime.registry import Registry
from odoo.service.transaction import retrying

from .conftest import requires_pg


@requires_pg
def test_commit_rejection_resets_real_orm_state(base_db, monkeypatch):
    registry = Registry(base_db)
    monkeypatch.setattr("odoo.service.transaction.time.sleep", lambda _: None)
    with registry.cursor() as cr, db_connect(base_db).cursor() as other:
        env = api.Environment(cr, 1, {})
        partners = env["res.partner"].create(
            [{"name": "retry original"}, {"name": "retry peer"}]
        )
        cr.execute(
            "CREATE TABLE retry_orm_probe (id integer PRIMARY KEY, value integer)"
        )
        cr.execute("INSERT INTO retry_orm_probe VALUES (1, 0), (2, 0)")
        cr.commit()
        attempts = []
        rejected = []
        original_commit = cr.commit

        def commit():
            try:
                original_commit()
            except errors.SerializationFailure:
                rejected.append(True)
                raise

        monkeypatch.setattr(cr, "commit", commit)

        def handler():
            cr.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cr.execute("SELECT sum(value) FROM retry_orm_probe")
            snapshot = cr.fetchone()[0]
            attempts.append((snapshot, partners[0].name))
            if len(attempts) == 1:
                other.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                other.execute("SELECT sum(value) FROM retry_orm_probe")
                assert other.fetchone()[0] == 0
            partners[0].name = f"attempt {len(attempts)}"
            env.flush_all()
            cr.execute("UPDATE retry_orm_probe SET value = value + 1 WHERE id = 1")
            if len(attempts) == 1:
                other.execute("UPDATE retry_orm_probe SET value = 1 WHERE id = 2")
                other.commit()
            return partners[0].name

        assert retrying(handler, env) == "attempt 2"
        assert rejected == [True]
        assert attempts == [(0, "retry original"), (1, "retry original")]
        env.invalidate_all()
        assert partners[0].name == "attempt 2"
        cr.execute("SELECT value FROM retry_orm_probe ORDER BY id")
        assert cr.fetchall() == [(1,), (1,)]
