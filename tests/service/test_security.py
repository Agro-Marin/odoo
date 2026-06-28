"""Pure-pytest tests for ``odoo.service.security``.

Covers ``check_session()``: expiry, token validation, and device-log update.
No live database required — all ORM calls are mocked.

Run with::

    python -m pytest core/tests/service/ -v
"""

import time
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(scope="module")
def sec():
    """Return ``odoo.service.security``, imported once per session."""
    import odoo.service.security as mod  # noqa: PLC0415

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


def _make_env(expected_token: str):
    """Build a minimal Environment mock returning ``expected_token`` from compute."""
    env = MagicMock()
    user = MagicMock()
    user._compute_session_token.return_value = expected_token
    env.__getitem__ = MagicMock(return_value=MagicMock(browse=MagicMock(return_value=user)))
    return env, user


class TestCheckSession:
    """``check_session()``: session expiry, token verification, device-log update."""

    def test_expired_deletion_time_returns_false(self, sec) -> None:
        """A session whose deletion_time is in the past must be rejected."""
        session = _FakeSession(uid=1, sid="abc", token="tok", deletion_time=time.time() - 1)
        env, _ = _make_env("tok")
        assert sec.check_session(session, env) is False

    def test_token_mismatch_returns_false(self, sec) -> None:
        """A session whose token doesn't match the computed HMAC is rejected."""
        session = _FakeSession(uid=1, sid="abc", token="wrong")
        env, _ = _make_env("correct")
        with patch("odoo.service.security.consteq", return_value=False):
            result = sec.check_session(session, env)
        assert result is False

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
        with patch("odoo.service.security.consteq", return_value=True):
            result = sec.check_session(session, env)
        assert result is True
        # device log must not be touched when request=None
        env.__getitem__.return_value.browse.return_value  # ensure no _update_device calls
        # The env["res.device.log"] key should never have been accessed
        accessed_keys = [c.args[0] for c in env.__getitem__.call_args_list]
        assert "res.device.log" not in accessed_keys

    def test_valid_session_with_request_updates_device(self, sec) -> None:
        """On a valid session with a live request, ``_update_device`` must be called."""
        session = _FakeSession(uid=1, sid="abc", token="good_token")

        env = MagicMock()
        user = MagicMock()
        user._compute_session_token.return_value = "good_token"
        device_log = MagicMock()

        def env_getitem(key):
            if key == "res.users":
                return MagicMock(browse=MagicMock(return_value=user))
            if key == "res.device.log":
                return device_log
            return MagicMock()

        env.__getitem__ = MagicMock(side_effect=env_getitem)

        mock_request = MagicMock()
        with patch("odoo.service.security.consteq", return_value=True):
            result = sec.check_session(session, env, request=mock_request)

        assert result is True
        device_log._update_device.assert_called_once_with(mock_request)

    def test_delete_old_sessions_always_called(self, sec) -> None:
        """``_delete_old_sessions()`` is invoked on every call, even before token check."""
        session = _FakeSession(uid=1, sid="abc", token="tok")
        env, _ = _make_env("tok")
        with patch("odoo.service.security.consteq", return_value=True):
            sec.check_session(session, env)
        session._delete_old_sessions.assert_called_once()
