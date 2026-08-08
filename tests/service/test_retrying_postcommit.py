from unittest.mock import MagicMock

import pytest

from odoo.service.transaction import retrying


@pytest.fixture
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


@pytest.fixture
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


class TestHookClosedCursorStillSignals:
    """A durable commit must announce itself even if a hook closed the cursor.

    The sibling of ``test_peers_are_signalled_when_the_commit_itself_succeeded``,
    reached through the *success* path instead of the exception path.

    ``Cursor.commit`` runs the SQL ``COMMIT`` and then ``postcommit.run()``. A
    hook that raises is handled: ``retrying`` sees the exception, notices
    ``commit_count`` advanced, and signals anyway. But a hook that *closes the
    cursor without raising* returns normally, and ``retrying``'s last line is

        if not env.cr.closed:
            env.registry.signal_changes()

    so the signal is skipped — for a transaction that is already durable. That
    is exactly the outcome the durable branch above exists to prevent: every
    other worker keeps serving a stale registry and ormcache for a committed
    change, with nothing recording it.

    Note the asymmetry in how much the two paths try: the durable branch signals
    inside ``suppress(Exception)`` (best-effort, because announcing matters),
    while this path declines to attempt it at all.
    """

    def _env_whose_hook_closes_the_cursor(self):
        env = MagicMock()
        env.cr.closed = False
        env.cr.flush = MagicMock()
        env.cr.rollback = MagicMock()
        env.cr.commit_count = 0

        def commit_then_hook_closes():
            env.cr.commit_count += 1  # durable
            env.cr.closed = True  # a post-commit hook closed it, no exception

        env.cr.commit = MagicMock(side_effect=commit_then_hook_closes)
        env.transaction.reset = MagicMock()
        env.registry.reset_changes = MagicMock()
        env.registry.signal_changes = MagicMock()
        env.registry.values.return_value = []
        env._.side_effect = lambda tmpl, *a: tmpl % a if a else tmpl
        return env

    def test_the_commit_is_durable(self):
        """Guard the guard: if the commit never ran, the test below is vacuous."""
        env = self._env_whose_hook_closes_the_cursor()
        retrying(lambda: "ok", env)
        assert env.cr.commit_count == 1
        assert env.cr.closed is True

    def test_peers_are_signalled(self):
        env = self._env_whose_hook_closes_the_cursor()
        retrying(lambda: "ok", env)
        env.registry.signal_changes.assert_called_once()
