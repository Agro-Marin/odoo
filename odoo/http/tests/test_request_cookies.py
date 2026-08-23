"""``request.cookies`` must not freeze an answer taken before sanitisation.

``ir.http._sanitize_cookies`` is a security hook: addons drop from it the
cookies a visitor has not consented to. It needs a registry, and ``_serve_db``
only assigns ``request.registry`` part-way through the request -- after
``_post_init``, after the static branch, at the moment the registry cursor
opens. A ``cached_property`` therefore stored whatever was true at the *first*
read, so any reader that ran before that point silently pinned the unsanitised
cookies for the rest of the request, security hook and all.
"""

import types
from typing import Any

import pytest
import werkzeug.datastructures

from odoo.http.request_class import Request


class _Registry(dict):
    def __init__(self, dropped):
        super().__init__()
        self.dropped = dropped
        self.calls = 0
        self["ir.http"] = self

    def _sanitize_cookies(self, cookies):
        self.calls += 1
        for name in self.dropped:
            cookies.poplist(name)


def _request(**cookies) -> Any:
    request: Any = object.__new__(Request)
    request.registry = None
    request._cookies_memo = None
    request.httprequest = types.SimpleNamespace(
        cookies=werkzeug.datastructures.MultiDict(cookies)
    )
    return request


def test_without_a_registry_every_cookie_is_visible():
    request = _request(session_id="s", tracking="t")
    assert request.cookies["tracking"] == "t"


def test_a_read_before_the_registry_does_not_pin_the_unsanitised_answer():
    request = _request(session_id="s", tracking="t")
    assert "tracking" in request.cookies

    request.registry = _Registry({"tracking"})
    assert "tracking" not in request.cookies
    assert request.cookies["session_id"] == "s"


def test_the_sanitised_answer_is_computed_once():
    request = _request(session_id="s", tracking="t")
    registry = _Registry({"tracking"})
    request.registry = registry

    for _ in range(5):
        assert "tracking" not in request.cookies
    assert registry.calls == 1


def test_the_answer_is_still_immutable():
    request = _request(session_id="s")
    cookies = request.cookies
    assert isinstance(cookies, werkzeug.datastructures.ImmutableMultiDict)
    with pytest.raises(TypeError):
        cookies["session_id"] = "other"


def test_dropping_the_registry_again_reexposes_nothing_stale():
    request = _request(session_id="s", tracking="t")
    request.registry = _Registry({"tracking"})
    assert "tracking" not in request.cookies

    request.registry = None
    assert "tracking" in request.cookies
