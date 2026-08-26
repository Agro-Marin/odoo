from unittest.mock import MagicMock

import pytest

from odoo.service.transaction import retrying

from .conftest import durable_then_close, durable_then_raise, retrying_env


@pytest.fixture
def committed_env():
    return retrying_env(on_commit=durable_then_raise())


@pytest.fixture
def failed_commit_env(committed_env):
    committed_env.cr.commit = MagicMock(
        side_effect=RuntimeError("could not serialize access")
    )
    return committed_env


def test_successful_commit_signals_peers(committed_env):
    committed_env.cr.commit = MagicMock()
    assert retrying(lambda: "ok", committed_env) == "ok"
    committed_env.registry.signal_changes.assert_called_once()


def test_post_commit_failure_propagates(committed_env):
    with pytest.raises(RuntimeError, match="post-commit hook failed"):
        retrying(lambda: "ok", committed_env)


def test_peers_are_signalled_when_the_commit_itself_succeeded(committed_env):
    with pytest.raises(RuntimeError):
        retrying(lambda: "ok", committed_env)

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
    with pytest.raises(RuntimeError, match="could not serialize access"):
        retrying(lambda: "ok", failed_commit_env)

    failed_commit_env.registry.reset_changes.assert_called()
    failed_commit_env.registry.signal_changes.assert_not_called()


class TestClosedCursorIsNotSilentSuccess:
    def _closed_env(self):
        return retrying_env(closed=True)

    def test_result_is_still_returned(self):
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
    def _env_whose_hook_closes_the_cursor(self):
        return retrying_env(on_commit=durable_then_close)

    def test_the_commit_is_durable(self):
        env = self._env_whose_hook_closes_the_cursor()
        retrying(lambda: "ok", env)
        assert env.cr.commit_count == 1
        assert env.cr.closed is True

    def test_peers_are_signalled(self):
        env = self._env_whose_hook_closes_the_cursor()
        retrying(lambda: "ok", env)
        env.registry.signal_changes.assert_called_once()
