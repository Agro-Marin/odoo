import types
from typing import Any

import pytest
import werkzeug.datastructures

from odoo.http._response import _RequestResponseMixin


def _this(db=None, env=None):
    """A stand-in carrying the two attributes ``redirect`` reads, and the one
    method ``redirect_query`` calls back into."""
    obj: Any = types.SimpleNamespace(db=db, env=env)
    obj.redirect = lambda loc, code=303, local=True: _RequestResponseMixin.redirect(
        obj, loc, code=code, local=local
    )
    return obj


def _redirect(location, *, local=True, db=None, env=None):
    return _RequestResponseMixin.redirect(_this(db, env), location, local=local)


def _location(location, **kw):
    return _redirect(location, **kw).headers["Location"]


HOSTILE = [
    "https://evil.com/x",
    "//evil.com/x",
    "///evil.com/x",
    "\\\\evil.com/x",
    "/\\evil.com/x",
    "/\\/evil.com",
    "http:evil.com",
    "https:/evil.com",
    "javascript:alert(1)",
    "data:text/html,<script>",
    "  //evil.com",
    "//evil.com@good.com/",
    "\\/\\/evil.com",
    "http://good.com\\@evil.com",
]


@pytest.mark.parametrize("location", HOSTILE)
def test_a_local_redirect_can_never_leave_this_origin(location):
    r"""`local=True` is the promise the whole open-redirect defence rests on.

    Judged with the BROWSER's rules, not Python's. WHATWG treats a backslash as
    a path separator, so `/\evil.com` is an authority and leaves the origin --
    while `urllib.parse.urlsplit` reports it as an ordinary path and would call
    it safe. Asserting through urlsplit alone makes this test pass with the
    backslash removed from the sanitiser's `lstrip`, which is the one character
    doing the work.
    """
    import urllib.parse

    result = _location(location)
    assert result.startswith("/"), result

    as_a_browser_reads_it = result.replace("\\", "/")
    parsed = urllib.parse.urlsplit(as_a_browser_reads_it)
    assert not parsed.scheme, result
    assert not parsed.netloc, result
    assert not as_a_browser_reads_it.startswith("//"), result


def test_a_newline_cannot_reach_the_location_header():
    """CRLF is dropped by urlsplit before werkzeug ever sees the value.

    Pinned because it is stdlib behaviour the sanitiser leans on rather than
    something this function does itself.
    """
    result = _location("/a\r\nX-Injected: 1")
    assert "\r" not in result and "\n" not in result, repr(result)


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("", "/"),
        ("/", "/"),
        ("relative/path", "/relative/path"),
        ("/already/absolute", "/already/absolute"),
        ("/keeps?a=1&b=2", "/keeps?a=1&b=2"),
        ("/keeps#frag", "/keeps#frag"),
        # a hostile value inside the QUERY is a value, not a target
        ("/legit?next=//evil.com", "/legit?next=//evil.com"),
    ],
)
def test_a_legitimate_local_target_is_untouched(location, expected):
    assert _location(location) == expected


def test_local_false_leaves_an_absolute_url_alone():
    assert _location("https://partner.example/cb", local=False) == (
        "https://partner.example/cb"
    )


def test_a_database_bound_request_delegates_to_ir_http():
    """`ir.http._redirect` is the override point http_routing uses for langs."""
    seen = {}

    def _ir_redirect(location, code=303):
        seen["location"] = location
        return "delegated"

    env: Any = {"ir.http": types.SimpleNamespace(_redirect=_ir_redirect)}
    assert _redirect("//evil.com/x", db="db", env=env) == "delegated"
    assert seen["location"] == "/x", "the sanitising must happen BEFORE delegation"


def test_redirect_query_appends_without_losing_the_fragment():
    this = _this()
    res = _RequestResponseMixin.redirect_query(this, "/web/login#tab", {"r": "/a b"})
    location = res.headers["Location"]
    assert location.startswith("/web/login?r=")
    assert location.endswith("#tab")
    assert "%2Fa+b" in location or "%2Fa%20b" in location, location


def test_redirect_query_preserves_repeated_keys():
    this = _this()
    query = werkzeug.datastructures.MultiDict([("t", "1"), ("t", "2")])
    location = _RequestResponseMixin.redirect_query(this, "/x", query).headers[
        "Location"
    ]
    assert location.count("t=") == 2, location


def test_redirect_query_uses_an_ampersand_when_the_url_already_has_one():
    this = _this()
    location = _RequestResponseMixin.redirect_query(this, "/x?a=1", {"b": "2"}).headers[
        "Location"
    ]
    assert location == "/x?a=1&b=2", location
