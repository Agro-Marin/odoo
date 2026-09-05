from unittest.mock import MagicMock

import pytest
from psycopg import OperationalError, errors

from odoo.service.transaction import retrying

from .conftest import durable_then_raise, retrying_env


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr("odoo.service.transaction.time.sleep", lambda _: None)


@pytest.mark.parametrize(
    "error", [errors.SerializationFailure, errors.DeadlockDetected]
)
def test_commit_rejection_replays_after_recovery(error):
    events = []
    env = retrying_env()
    env.cr.commit_count = 7  # The cursor may have committed earlier requests.
    participant = MagicMock()
    env.cr.rollback.side_effect = lambda: events.append("rollback")
    env.transaction.reset.side_effect = lambda: events.append("reset")
    env.registry.reset_changes.side_effect = lambda: events.append("registry")
    participant.on_rollback.side_effect = lambda _: events.append("participant")
    participant.on_retry.side_effect = lambda _: events.append("rewind")

    def commit():
        events.append("commit")
        if events.count("commit") == 1:
            raise error("commit rejected")
        env.cr.commit_count += 1

    def handler():
        events.append("handler")
        return events.count("handler")

    env.cr.commit.side_effect = commit

    assert retrying(handler, env, participant) == 2
    assert events == [
        "handler",
        "commit",
        "rollback",
        "reset",
        "registry",
        "participant",
        "rewind",
        "handler",
        "commit",
    ]
    assert env.cr.commit_count == 8
    env.registry.signal_changes.assert_called_once()


@pytest.mark.parametrize(
    "error", [errors.SerializationFailure, errors.DeadlockDetected]
)
def test_retryable_postcommit_error_never_replays_durable_work(error):
    exc = error("hook failed after commit")
    env = retrying_env(on_commit=durable_then_raise(exc))
    handler = MagicMock(return_value="done")
    participant = MagicMock()

    with pytest.raises(error) as caught:
        retrying(handler, env, participant)

    assert caught.value is exc
    handler.assert_called_once()
    env.cr.rollback.assert_not_called()
    env.transaction.reset.assert_not_called()
    env.registry.reset_changes.assert_not_called()
    env.registry.signal_changes.assert_called_once()
    participant.on_retry.assert_not_called()


@pytest.mark.parametrize("failed_reset", ["transaction", "registry"])
def test_failed_state_reset_refuses_replay(failed_reset):
    env = retrying_env()
    reset = (
        env.transaction.reset
        if failed_reset == "transaction"
        else env.registry.reset_changes
    )
    reset.side_effect = RuntimeError("recovery failed")
    handler = MagicMock(side_effect=[errors.SerializationFailure(), "unsafe replay"])

    with pytest.raises(RuntimeError, match="recovery failed"):
        retrying(handler, env)

    handler.assert_called_once()
    env.cr.commit.assert_not_called()


def test_connection_closed_during_rollback_refuses_replay():
    env = retrying_env()
    env.cr.rollback.side_effect = lambda: setattr(env.cr, "closed", True)
    handler = MagicMock(side_effect=[errors.SerializationFailure(), "unsafe replay"])

    with pytest.raises(errors.SerializationFailure):
        retrying(handler, env)

    handler.assert_called_once()
    env.cr.commit.assert_not_called()


def test_unknown_commit_outcome_is_not_replayed():
    env = retrying_env()
    env.cr.commit.side_effect = OperationalError("connection lost during commit")
    handler = MagicMock(return_value="done")

    with pytest.raises(OperationalError, match="connection lost"):
        retrying(handler, env)

    handler.assert_called_once()
    env.registry.signal_changes.assert_not_called()


def test_handler_that_committed_cannot_be_replayed():
    env = retrying_env()

    def handler():
        env.cr.commit_count += 1
        raise errors.SerializationFailure("later transaction failed")

    with pytest.raises(errors.SerializationFailure):
        retrying(handler, env)

    assert env.cr.commit_count == 1
    env.cr.rollback.assert_not_called()
