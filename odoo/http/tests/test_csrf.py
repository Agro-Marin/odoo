import time

import pytest

from odoo.http._csrf import _RequestCsrfMixin
from odoo.http.constants import (
    CSRF_TOKEN_MAX_AGE,
    SESSION_LIFETIME,
    STORED_SESSION_BYTES,
)

# `odoo/http/_csrf.py` had no tests. It is 52 lines that decide whether a
# state-changing request is accepted, so "small" is not the same as "does not
# need pinning" -- every branch below is a security decision.
#
# The token is `hmac_sha256(secret, sid[:STORED_SESSION_BYTES] + max_ts) + "o" + max_ts`.
# Binding to a *prefix* of the sid is deliberate, not an oversight: SessionStore
# .rotate(soft=True) rebuilds the sid as `sid[:STORED_SESSION_BYTES] +
# new_tail` (session.py:111), so the static head is the stable session
# identity. A soft rotation therefore keeps tokens valid, and a hard rotation
# (session.py:113, taken on authenticate() and logout()) invalidates them.
# Those two behaviours are the point of the design and are pinned below.

SECRET = "s3cr3t-database-secret"
SID = "a" * 32 + "b" * 32  # 64 chars: a static head and a rotating tail


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
    # soft rotate keeps sid[:STORED_SESSION_BYTES] and regenerates the tail.
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
    # hard rotate (authenticate / logout) regenerates the whole sid.
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
        "deadbeef",  # no separator
        "deadbeefo",  # empty timestamp
        "deadbeefonotanumber",
        "9999999999",  # digits only, no separator: rpartition yields hm=""
    ],
)
def test_malformed_tokens_are_rejected_without_raising(bad):
    assert _FakeRequest().validate_csrf(bad) is False


def test_empty_hmac_with_a_future_timestamp_is_rejected():
    # rpartition("o") on a separator-less token yields hm="", and "".isascii()
    # is True, so this reaches consteq(). It must still fail.
    assert _FakeRequest().validate_csrf(str(int(time.time()) + 10_000)) is False


def test_missing_database_secret_raises_rather_than_allowing():
    req = _FakeRequest(secret=None)
    with pytest.raises(ValueError):
        req.csrf_token()
    with pytest.raises(ValueError):
        req.validate_csrf("anything-non-empty")


def test_no_secret_still_short_circuits_on_an_empty_token():
    # The falsy-token check runs before the secret lookup, so an unconfigured
    # database rejects rather than raising on the common path.
    assert _FakeRequest(secret=None).validate_csrf("") is False


def test_minting_touches_a_new_session_so_the_sid_is_persisted():
    # Without this the token would be bound to a sid the store never saved.
    req = _FakeRequest(is_new=True)
    req.csrf_token()
    assert req.session.touched == 1
    req2 = _FakeRequest(is_new=False)
    req2.csrf_token()
    assert req2.session.touched == 0


def test_token_max_age_vastly_exceeds_session_lifetime():
    # Pinned as a QUESTION, not an endorsement. A CSRF token is valid for a
    # year; the session it is bound to expires in a week. For a continuously
    # active session the static sid prefix survives every soft rotation, so a
    # token leaked once stays valid for the full year — rotation does not
    # invalidate it, by design (see test_token_survives_a_soft_rotation).
    #
    # If CSRF_TOKEN_MAX_AGE is ever brought in line with SESSION_LIFETIME, this
    # test failing is the intended signal: update the ratio and delete this note.
    assert CSRF_TOKEN_MAX_AGE == 60 * 60 * 24 * 365
    assert SESSION_LIFETIME == 60 * 60 * 24 * 7
    assert CSRF_TOKEN_MAX_AGE // SESSION_LIFETIME == 52


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
