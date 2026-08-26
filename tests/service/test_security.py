import time
from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="module")
def sec():
    import odoo.service.security as mod

    return mod


class _FakeSession:
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
    def test_expired_deletion_time_returns_false(self, sec) -> None:
        session = _FakeSession(
            uid=1, sid="abc", token="tok", deletion_time=time.time() - 1
        )
        env, _ = _make_env("tok")
        assert sec.check_session(session, env) is False

    def test_token_mismatch_returns_false(self, sec) -> None:
        session = _FakeSession(uid=1, sid="abc", token="wrong")
        env, _ = _make_env("correct")
        assert sec.check_session(session, env) is False

    def test_non_string_token_is_refused_before_the_comparison(self, sec) -> None:
        for bad in (None, 42, b"tok", ["tok"]):
            session = _FakeSession(uid=1, sid="abc", token=bad)
            env, _ = _make_env("correct")
            assert sec.check_session(session, env) is False, bad

    def test_no_expected_token_returns_false(self, sec) -> None:
        session = _FakeSession(uid=1, sid="abc", token="anything")
        env, _ = _make_env("")
        result = sec.check_session(session, env)
        assert result is False

    def test_valid_session_no_request_returns_true(self, sec) -> None:
        session = _FakeSession(uid=1, sid="abc", token="good_token")
        env, _ = _make_env("good_token")
        result = sec.check_session(session, env)
        assert result is True
        accessed_keys = [c.args[0] for c in env.__getitem__.call_args_list]
        assert "res.device.log" not in accessed_keys

    def test_valid_session_with_request_updates_device(self, sec) -> None:
        session = _FakeSession(uid=1, sid="abc", token="good_token")

        device_log = MagicMock()
        env, _ = _make_env("good_token", device_log=device_log)

        mock_request = MagicMock()
        result = sec.check_session(session, env, request=mock_request)

        assert result is True
        device_log._update_device.assert_called_once_with(mock_request)

    def test_device_log_failure_keeps_the_session_authenticated(self, sec) -> None:
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
        session = _FakeSession(uid=1, sid="abc", token="tok")
        env, _ = _make_env("tok")
        sec.check_session(session, env)
        session._delete_old_sessions.assert_called_once()
