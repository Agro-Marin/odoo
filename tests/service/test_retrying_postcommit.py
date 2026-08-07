"""A failing post-commit hook must not swallow the peer-invalidation signal.

``Cursor.commit`` (``odoo/db/cursor.py:698-714``) issues the SQL ``COMMIT``
first and runs ``self.postcommit.run()`` *after* it.  So a post-commit hook that
raises does so with the transaction already durable.

``retrying()`` (``odoo/service/transaction.py:208-222``) treats any exception out
of ``env.cr.commit()`` as a failed commit: it calls ``_reset_env_state(env)`` --
which runs ``registry.reset_changes()`` and clears ``registry_invalidated`` --
and re-raises, so ``env.registry.signal_changes()`` on the next line never runs.

The result, verified against a live database before this test was written: the
rows are committed, ``registry_invalidated`` is cleared locally, and no row is
inserted into ``orm_signaling_registry``.  Every *other* worker process therefore
keeps serving its old registry and ormcache for a schema change that is already
committed, and nothing anywhere records that it happened.

The failure is only observable across processes, which is why it needs pinning
here rather than in an integration test: a single-worker run cannot see it.
"""

from unittest.mock import MagicMock

import pytest

from odoo.service.transaction import retrying


@pytest.fixture()
def committed_env():
    """An env whose SQL COMMIT succeeds but whose post-commit hooks raise.

    Mirrors ``Cursor.commit``: the COMMIT lands (so ``commit_count`` is bumped)
    and only then does a hook blow up.
    """
    env = MagicMock()
    env.cr._closed = False
    env.cr.closed = False
    env.cr.flush = MagicMock()
    env.cr.rollback = MagicMock()
    env.cr.commit_count = 0

    def commit_then_hook_fails():
        env.cr.commit_count += 1  # the transaction is now durable
        raise RuntimeError("post-commit hook failed")

    env.cr.commit = MagicMock(side_effect=commit_then_hook_fails)
    env.transaction.reset = MagicMock()
    env.registry.reset_changes = MagicMock()
    env.registry.signal_changes = MagicMock()
    env.registry.values.return_value = []
    env._.side_effect = lambda tmpl, *a: tmpl % a if a else tmpl
    return env


@pytest.fixture()
def failed_commit_env(committed_env):
    """An env whose SQL COMMIT itself fails -- nothing durable happened."""
    committed_env.cr.commit = MagicMock(
        side_effect=RuntimeError("could not serialize access")
    )
    return committed_env


def test_successful_commit_signals_peers(committed_env):
    """Baseline: the signal is what tells other workers to reload."""
    committed_env.cr.commit = MagicMock()  # clean commit
    assert retrying(lambda: "ok", committed_env) == "ok"
    committed_env.registry.signal_changes.assert_called_once()


def test_post_commit_failure_propagates(committed_env):
    with pytest.raises(RuntimeError, match="post-commit hook failed"):
        retrying(lambda: "ok", committed_env)


def test_peers_are_signalled_when_the_commit_itself_succeeded(committed_env):
    with pytest.raises(RuntimeError):
        retrying(lambda: "ok", committed_env)

    # The data is durable, so the peers must be told regardless of the hook.
    committed_env.registry.signal_changes.assert_called_once()


def test_local_registry_state_is_not_rolled_back_after_a_durable_commit(
    committed_env,
):
    with pytest.raises(RuntimeError):
        retrying(lambda: "ok", committed_env)

    committed_env.registry.reset_changes.assert_not_called()


def test_a_genuinely_failed_commit_still_resets_and_does_not_signal(
    failed_commit_env,
):
    """The other half: nothing was committed, so nothing may be announced."""
    with pytest.raises(RuntimeError, match="could not serialize access"):
        retrying(lambda: "ok", failed_commit_env)

    failed_commit_env.registry.reset_changes.assert_called()
    failed_commit_env.registry.signal_changes.assert_not_called()


class TestClosedCursorIsNotSilentSuccess:
    """A closed cursor must be reported, not returned as an ordinary success.

    ``retrying`` skips the commit when ``env.cr.closed`` — correctly, since the
    connection is already back in the pool and committing would raise — and then
    returns the handler's result. So the handler ran, whatever it wrote is gone,
    the caller gets a normal return value, and nothing distinguishes it from a
    committed request. On the HTTP path that is a 200 with a payload over an
    uncommitted transaction.

    The skip stays; the silence does not.
    """

    def _closed_env(self):
        env = MagicMock()
        env.cr.closed = True
        env.cr.commit = MagicMock()
        env.cr.flush = MagicMock()
        env.registry.signal_changes = MagicMock()
        env.registry.values.return_value = []
        return env

    def test_result_is_still_returned(self, caplog):
        env = self._closed_env()
        assert retrying(lambda: "handler result", env) == "handler result"

    def test_commit_and_signal_are_skipped(self):
        env = self._closed_env()
        retrying(lambda: None, env)
        env.cr.commit.assert_not_called()
        env.registry.signal_changes.assert_not_called()

    def test_it_warns(self, caplog):
        import logging

        env = self._closed_env()
        with caplog.at_level(logging.WARNING):
            retrying(lambda: None, env)
        assert "NOT committed" in caplog.text
