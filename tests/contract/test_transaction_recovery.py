from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from psycopg import errors

from odoo.db import db_connect
from odoo.service.transaction import retrying

from .conftest import requires_pg


@requires_pg
def test_serialization_rejected_at_commit_replays_the_transaction(
    scratch_db, scratch_cursor, monkeypatch
):
    """A real write-skew conflict must fail at COMMIT, then replay cleanly."""
    cr = scratch_cursor
    cr.execute("CREATE TABLE retry_probe (id integer PRIMARY KEY, value integer)")
    cr.execute("INSERT INTO retry_probe VALUES (1, 0), (2, 0)")
    cr.commit()
    before = cr.commit_count
    env = SimpleNamespace(cr=cr, transaction=MagicMock(), registry=MagicMock())
    monkeypatch.setattr("odoo.service.transaction.time.sleep", lambda _: None)
    attempts = []
    commit_rejections = []
    original_commit = cr.commit

    def commit():
        try:
            original_commit()
        except errors.SerializationFailure as exc:
            commit_rejections.append(exc)
            raise

    monkeypatch.setattr(cr, "commit", commit)

    with db_connect(scratch_db).cursor() as other:

        def handler():
            cr.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cr.execute("SELECT sum(value) FROM retry_probe")
            attempts.append(cr.fetchone()[0])
            if len(attempts) == 1:
                other.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                other.execute("SELECT sum(value) FROM retry_probe")
                assert other.fetchone()[0] == 0
            cr.execute("UPDATE retry_probe SET value = value + 1 WHERE id = 1")
            if len(attempts) == 1:
                other.execute("UPDATE retry_probe SET value = 1 WHERE id = 2")
                other.commit()
            return attempts[-1]

        assert retrying(handler, env) == 1

    assert attempts == [0, 1], "replay must read a new snapshot"
    assert len(commit_rejections) == 1, "the failure must come from COMMIT"
    assert cr.commit_count == before + 1
    cr.execute("SELECT value FROM retry_probe ORDER BY id")
    assert cr.fetchall() == [(1,), (1,)], "the aborted write must not survive"
    env.registry.signal_changes.assert_called_once()


@requires_pg
def test_durable_postcommit_failure_does_not_duplicate_writes(scratch_cursor):
    cr = scratch_cursor
    cr.execute("CREATE TABLE retry_hook_probe (value integer)")
    cr.commit()
    before = cr.commit_count
    env = SimpleNamespace(cr=cr, transaction=MagicMock(), registry=MagicMock())
    attempts = []

    def hook():
        raise errors.SerializationFailure("postcommit callback failed")

    def handler():
        attempts.append(True)
        cr.execute("INSERT INTO retry_hook_probe VALUES (1)")
        cr.postcommit.add(hook)

    with pytest.raises(errors.SerializationFailure, match="postcommit callback"):
        retrying(handler, env)

    assert attempts == [True]
    assert cr.commit_count == before + 1
    cr.execute("SELECT value FROM retry_hook_probe")
    assert cr.fetchall() == [(1,)]
    env.registry.reset_changes.assert_not_called()
    env.registry.signal_changes.assert_called_once()
