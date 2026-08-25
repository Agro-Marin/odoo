"""Pure-pytest tests for ``odoo.service.security``.

Covers ``check_session()``: expiry, token validation, and device-log update.
No live database required — all ORM calls are mocked.

Run with::

    python -m pytest tests/service/ -v
"""

import time
from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="module")
def sec():
    """Return ``odoo.service.security``, imported once per session."""
    import odoo.service.security as mod

    return mod


class _FakeSession:
    """Minimal session stub that supports ``in`` and ``[]`` for deletion_time."""

    def __init__(self, uid, sid, token, deletion_time=None):
        self.uid = uid
        self.sid = sid
        self.session_token = token
        self._delete_old_sessions = MagicMock()
        self._data: dict = {}
        if deletion_time is not None:
            self._data["deletion_time"] = deletion_time

    def __contains__(self, key):
        return key in self._data

    def __getitem__(self, key):
        return self._data[key]


def _make_env(expected_token: str, device_log=None):
    """A minimal Environment mock whose user computes ``expected_token``.

    ``device_log`` supplies ``env["res.device.log"]`` when a test drives the
    request path.  It used to be unsupported, so the three tests that need one
    each rebuilt this whole block by hand — the copies then had to be kept in
    step by eye.
    """
    env = MagicMock()
    user = MagicMock()
    user._compute_session_token.return_value = expected_token
    users = MagicMock(browse=MagicMock(return_value=user))

    def getitem(key):
        if key == "res.users":
            return users
        if key == "res.device.log" and device_log is not None:
            return device_log
        return MagicMock()

    env.__getitem__ = MagicMock(side_effect=getitem)
    return env, user


class TestCheckSession:
    """``check_session()``: session expiry, token verification, device-log update."""

    def test_expired_deletion_time_returns_false(self, sec) -> None:
        """A session whose deletion_time is in the past must be rejected."""
        session = _FakeSession(
            uid=1, sid="abc", token="tok", deletion_time=time.time() - 1
        )
        env, _ = _make_env("tok")
        assert sec.check_session(session, env) is False

    def test_token_mismatch_returns_false(self, sec) -> None:
        """A session whose token doesn't match the computed HMAC is rejected.

        ``consteq`` is deliberately NOT patched here.  It is a pure function of
        two strings and returns the same answer either way, so a stub buys
        nothing — and costs the assertion: with it in place ``check_session``
        may compare *any* pair of values and still pass.  Verified by mutation:
        ``actual = session.session_token`` -> ``session.sid`` left all 887 tests
        green while the stubs were there, and fails now.
        """
        session = _FakeSession(uid=1, sid="abc", token="wrong")
        env, _ = _make_env("correct")
        assert sec.check_session(session, env) is False

    def test_non_string_token_is_refused_before_the_comparison(self, sec) -> None:
        """``session_token`` arrives from storage and need not be a ``str``.

        The ``isinstance(actual, str)`` guard is what stops one reaching
        ``consteq``, where a non-``str`` raises rather than returning False —
        turning a uniform ``False`` into a distinguishable error.  Verified by
        mutation: deleting the guard left the suite green.
        """
        for bad in (None, 42, b"tok", ["tok"]):
            session = _FakeSession(uid=1, sid="abc", token=bad)
            env, _ = _make_env("correct")
            assert sec.check_session(session, env) is False, bad

    def test_no_expected_token_returns_false(self, sec) -> None:
        """If ``_compute_session_token`` returns empty/None, reject immediately."""
        session = _FakeSession(uid=1, sid="abc", token="anything")
        env, _ = _make_env("")  # falsy expected
        result = sec.check_session(session, env)
        assert result is False

    def test_valid_session_no_request_returns_true(self, sec) -> None:
        """Matching token with no HTTP request returns True without touching device log."""
        session = _FakeSession(uid=1, sid="abc", token="good_token")
        env, _ = _make_env("good_token")
        result = sec.check_session(session, env)
        assert result is True
        # device log must not be touched when request=None
        accessed_keys = [c.args[0] for c in env.__getitem__.call_args_list]
        assert "res.device.log" not in accessed_keys

    def test_valid_session_with_request_updates_device(self, sec) -> None:
        """On a valid session with a live request, ``_update_device`` must be called."""
        session = _FakeSession(uid=1, sid="abc", token="good_token")

        device_log = MagicMock()
        env, _ = _make_env("good_token", device_log=device_log)

        mock_request = MagicMock()
        result = sec.check_session(session, env, request=mock_request)

        assert result is True
        device_log._update_device.assert_called_once_with(mock_request)

    def test_device_log_failure_keeps_the_session_authenticated(self, sec) -> None:
        """A failing ``_update_device`` must NOT cost the user their session.

        The device log is bookkeeping — a telemetry row about which device is
        in use — while ``check_session`` is the gate every authenticated request
        passes through.  Letting a write failure there propagate would turn a
        full ``res.device.log`` table, a lock timeout or a serialization failure
        into an instant logout for every user on the instance, which is why the
        call is wrapped in ``except Exception``.

        That wrapper was the one uncovered line in the module, and the only test
        touching ``_update_device`` drives the SUCCESS path: verified by
        mutation, narrowing the catch to ``except ZeroDivisionError`` left the
        whole 760-test suite green.
        """
        session = _FakeSession(uid=1, sid="abc", token="good_token")

        device_log = MagicMock()
        device_log._update_device.side_effect = RuntimeError("device log table full")
        env, _ = _make_env("good_token", device_log=device_log)

        mock_request = MagicMock()
        result = sec.check_session(session, env, request=mock_request)

        assert result is True, (
            "a device-log write failure logged the user out; the session was "
            "valid and the device log is not part of the auth decision"
        )
        device_log._update_device.assert_called_once_with(mock_request)

    def test_device_log_failure_is_logged_not_silently_swallowed(
        self, sec, caplog
    ) -> None:
        """Keeping the session must not make the failure invisible: an operator
        investigating an empty device log needs the warning to find it."""
        import logging

        session = _FakeSession(uid=1, sid="abc", token="good_token")
        device_log = MagicMock()
        device_log._update_device.side_effect = RuntimeError("device log table full")
        env, _ = _make_env("good_token", device_log=device_log)

        with caplog.at_level(logging.WARNING, logger="odoo.service.security"):
            assert sec.check_session(session, env, request=MagicMock()) is True

        assert any(r.levelno >= logging.WARNING for r in caplog.records), (
            "the swallowed device-log failure produced no operator-visible record"
        )

    def test_delete_old_sessions_always_called(self, sec) -> None:
        """``_delete_old_sessions()`` is invoked on every call, even before token check."""
        session = _FakeSession(uid=1, sid="abc", token="tok")
        env, _ = _make_env("tok")
        sec.check_session(session, env)
        session._delete_old_sessions.assert_called_once()
