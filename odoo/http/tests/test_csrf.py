import time

import pytest

from odoo.http._csrf import _RequestCsrfMixin
from odoo.http.constants import (
    CSRF_TOKEN_MAX_AGE,
    SESSION_LIFETIME,
    STORED_SESSION_BYTES,
)

SECRET = "s3cr3t-database-secret"
SID = "a" * 32 + "b" * 32


class _FakeParam:
    def __init__(self, secret):
        self._secret = secret

    def sudo(self):
        return self

    def get_param(self, key):
        assert key == "database.secret"
        return self._secret


class _FakeEnv(dict):
    pass


class _FakeSession:
    def __init__(self, sid=SID, is_new=False):
        self.sid = sid
        self.is_new = is_new
        self.touched = 0

    def touch(self):
        self.touched += 1


class _FakeRequest(_RequestCsrfMixin):
    def __init__(self, secret=SECRET, sid=SID, is_new=False):
        self.env = _FakeEnv({"ir.config_parameter": _FakeParam(secret)})
        self.session = _FakeSession(sid, is_new)


def test_a_freshly_minted_token_validates():
    req = _FakeRequest()
    assert req.validate_csrf(req.csrf_token()) is True


def test_token_survives_a_soft_rotation():
    req = _FakeRequest()
    token = req.csrf_token()
    req.session.sid = SID[:STORED_SESSION_BYTES] + "z" * (
        len(SID) - STORED_SESSION_BYTES
    )
    assert req.validate_csrf(token) is True, (
        "a soft rotation must not invalidate outstanding CSRF tokens — that is "
        "why the token binds the static sid prefix rather than the whole sid"
    )


def test_token_dies_on_a_hard_rotation():
    req = _FakeRequest()
    token = req.csrf_token()
    req.session.sid = "c" * len(SID)
    assert req.validate_csrf(token) is False


def test_token_is_not_transferable_between_sessions():
    token = _FakeRequest(sid=SID).csrf_token()
    other = _FakeRequest(sid="d" * len(SID))
    assert other.validate_csrf(token) is False


def test_token_from_a_different_secret_is_rejected():
    token = _FakeRequest(secret="secret-one").csrf_token()
    assert _FakeRequest(secret="secret-two").validate_csrf(token) is False


def test_expired_token_is_rejected():
    req = _FakeRequest()
    token = req.csrf_token(time_limit=-10)
    assert req.validate_csrf(token) is False


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "",
        "garbage",
        "o",
        "o123",
        "deadbeef",
        "deadbeefo",
        "deadbeefonotanumber",
        "9999999999",
    ],
)
def test_malformed_tokens_are_rejected_without_raising(bad):
    assert _FakeRequest().validate_csrf(bad) is False


def test_empty_hmac_with_a_future_timestamp_is_rejected():
    assert _FakeRequest().validate_csrf(str(int(time.time()) + 10_000)) is False


def test_missing_database_secret_raises_rather_than_allowing():
    req = _FakeRequest(secret=None)
    with pytest.raises(ValueError):
        req.csrf_token()
    with pytest.raises(ValueError):
        req.validate_csrf("anything-non-empty")


def test_no_secret_still_short_circuits_on_an_empty_token():
    assert _FakeRequest(secret=None).validate_csrf("") is False


def test_minting_touches_a_new_session_so_the_sid_is_persisted():
    req = _FakeRequest(is_new=True)
    req.csrf_token()
    assert req.session.touched == 1
    req2 = _FakeRequest(is_new=False)
    req2.csrf_token()
    assert req2.session.touched == 0


def test_token_max_age_vastly_exceeds_session_lifetime():
    assert CSRF_TOKEN_MAX_AGE == 60 * 60 * 24 * 365
    assert SESSION_LIFETIME == 60 * 60 * 24 * 7
    assert CSRF_TOKEN_MAX_AGE // SESSION_LIFETIME == 52


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
