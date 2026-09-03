import types

from odoo.http.core import _request_stack
from odoo.http.wrappers import _Response


class _DeniedIrHttp:
    def _is_allowed_cookie(self, cookie_type):
        return False


class _Env:
    def __getitem__(self, model):
        assert model == "ir.http"
        return _DeniedIrHttp()


def _push_denied_request():
    fake_request = types.SimpleNamespace(
        env=_Env(), httprequest=types.SimpleNamespace(is_secure=False)
    )
    _request_stack.push(fake_request)
    return fake_request


def test_a_denied_cookie_is_not_given_a_year_long_expiry():
    _push_denied_request()
    try:
        response = _Response("body")
        response.set_cookie("utm_campaign", "abc", cookie_type="optional")
    finally:
        _request_stack.pop()

    (header,) = response.headers.getlist("Set-Cookie")
    assert "Max-Age=0" in header
    assert "Expires=" in header
    # the Expires werkzeug derives from Max-Age=0 lands within the same
    # UTC day this test runs, not ~365 days out.
    import datetime

    now = datetime.datetime.now(tz=datetime.UTC)
    assert str(now.year) in header
    assert str(now.year + 1) not in header
