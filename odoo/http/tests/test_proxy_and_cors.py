"""Two things the HTTP layer told the outside world, and got wrong.

* how many reverse proxies it trusts — pinned at one, with no way to say
  otherwise, so behind two the client address read back is the inner proxy's
  and every rule keyed on it sees one address for the whole internet;
* which response headers a cross-origin caller may read — nothing emitted
  ``Access-Control-Expose-Headers``, so a ``cors=`` route's own headers were
  invisible to the JavaScript that asked for them.
"""

import types

import pytest

from odoo.http.application import _get_proxy_fix
from odoo.http.dispatcher import Dispatcher, HttpDispatcher
from odoo.http.wrappers import FutureResponse, no_content


def _environ(forwarded_for, forwarded_host=None, forwarded_proto=None):
    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": "/",
        "SERVER_NAME": "origin.example",
        "SERVER_PORT": "8069",
        "REMOTE_ADDR": "10.0.0.1",
        "wsgi.url_scheme": "http",
        "HTTP_X_FORWARDED_FOR": forwarded_for,
    }
    if forwarded_host:
        environ["HTTP_X_FORWARDED_HOST"] = forwarded_host
    if forwarded_proto:
        environ["HTTP_X_FORWARDED_PROTO"] = forwarded_proto
    return environ


def _noop(status, headers):
    pass


@pytest.mark.parametrize(
    ("hops", "expected"),
    [
        (1, "10.9.9.9"),
        (2, "203.0.113.7"),
        (3, "198.51.100.4"),
    ],
)
def test_the_trusted_hop_count_decides_the_client_address(hops, expected):
    # X-Forwarded-For: <client>, <outer proxy>, <inner proxy>
    environ = _environ("198.51.100.4, 203.0.113.7, 10.9.9.9")
    _get_proxy_fix(hops)(environ, _noop)
    assert environ["REMOTE_ADDR"] == expected


def test_asking_for_more_hops_than_the_header_holds_keeps_the_direct_peer():
    # werkzeug returns None rather than the first entry when the chain is
    # shorter than the trusted count, so an over-count degrades to the socket
    # address instead of believing a stranger.
    environ = _environ("203.0.113.7, 10.9.9.9")
    _get_proxy_fix(9)(environ, _noop)
    assert environ["REMOTE_ADDR"] == "10.0.0.1"


def test_over_counting_the_chain_is_still_forgeable_and_that_is_the_hazard():
    # One real proxy, but the server is told to trust three. A client that
    # sends two entries of its own makes the header
    #   <forged>, <forged>, <its real address appended by the proxy>
    # and the third-from-last is whatever it wanted. This is why the option's
    # help says to count the proxies that actually rewrite the header, and why
    # the default stays 1.
    environ = _environ("192.0.2.1, 192.0.2.2")
    environ["HTTP_X_FORWARDED_FOR"] += ", 10.9.9.9"
    _get_proxy_fix(3)(environ, _noop)
    assert environ["REMOTE_ADDR"] == "192.0.2.1"

    honest = _environ("192.0.2.1, 192.0.2.2")
    honest["HTTP_X_FORWARDED_FOR"] += ", 10.9.9.9"
    _get_proxy_fix(1)(honest, _noop)
    assert honest["REMOTE_ADDR"] == "10.9.9.9"


def test_the_hop_count_applies_to_host_and_proto_too():
    environ = _environ(
        "198.51.100.4, 203.0.113.7, 10.9.9.9",
        forwarded_host="outer.example, inner.example",
        forwarded_proto="https, http",
    )
    _get_proxy_fix(2)(environ, _noop)
    assert environ["HTTP_HOST"] == "outer.example"
    assert environ["wsgi.url_scheme"] == "https"


def test_the_same_hop_count_reuses_one_wrapper():
    assert _get_proxy_fix(2) is _get_proxy_fix(2)
    assert _get_proxy_fix(2) is not _get_proxy_fix(3)


class _Session(dict):
    can_save = True


def _dispatch_request(routing, headers=None, method="GET"):
    request = types.SimpleNamespace(
        future_response=FutureResponse(),
        session=_Session(),
        httprequest=types.SimpleNamespace(
            method=method,
            headers=headers or {},
        ),
    )
    rule = types.SimpleNamespace(endpoint=types.SimpleNamespace(routing=routing))
    HttpDispatcher(request).pre_dispatch(rule, {})
    return request.future_response.headers


def test_expose_headers_are_advertised_when_declared():
    headers = _dispatch_request(
        {
            "type": "http",
            "methods": ("GET",),
            "cors": "*",
            "cors_expose_headers": ("X-Total-Count", "X-Page"),
        }
    )
    assert headers["Access-Control-Expose-Headers"] == "X-Total-Count, X-Page"


def test_expose_headers_accepts_an_already_rendered_string():
    headers = _dispatch_request(
        {
            "type": "http",
            "methods": ("GET",),
            "cors": "*",
            "cors_expose_headers": "X-Total-Count",
        }
    )
    assert headers["Access-Control-Expose-Headers"] == "X-Total-Count"


def test_nothing_is_advertised_when_the_route_declares_none():
    headers = _dispatch_request({"type": "http", "methods": ("GET",), "cors": "*"})
    assert "Access-Control-Expose-Headers" not in headers


def test_expose_headers_are_not_advertised_without_cors():
    headers = _dispatch_request(
        {
            "type": "http",
            "methods": ("GET",),
            "cors_expose_headers": ("X-Total-Count",),
        }
    )
    assert "Access-Control-Expose-Headers" not in headers


def test_cors_expose_headers_is_a_declared_route_parameter():
    from odoo.http.routing import _KNOWN_ROUTING_PARAMETERS

    assert "cors_expose_headers" in _KNOWN_ROUTING_PARAMETERS


def test_a_bodyless_status_carries_no_content_type():
    response = no_content(headers=[("Allow", "GET, HEAD, OPTIONS")])
    assert response.status_code == 204
    assert "Content-Type" not in response.headers
    assert response.headers["Allow"] == "GET, HEAD, OPTIONS"


def test_the_headers_facade_can_delete():
    response = no_content()
    response.headers["X-Gone"] = "1"
    del response.headers["X-Gone"]
    assert "X-Gone" not in response.headers


def test_the_dispatcher_answers_options_without_a_content_type():
    import werkzeug.exceptions

    with pytest.raises(werkzeug.exceptions.HTTPException) as caught:
        _dispatch_request({"type": "http", "methods": ("POST",)}, method="OPTIONS")
    response = caught.value.response
    assert response is not None
    assert response.status_code == 204
    assert "Content-Type" not in response.headers
    assert response.headers["Allow"] == "POST, OPTIONS"


def test_the_cors_preflight_is_also_bodyless():
    import werkzeug.exceptions

    with pytest.raises(werkzeug.exceptions.HTTPException) as caught:
        _dispatch_request(
            {"type": "http", "methods": ("POST",), "cors": "*"},
            headers={"Origin": "https://x.example"},
            method="OPTIONS",
        )
    assert caught.value.response.status_code == 204
    assert "Content-Type" not in caught.value.response.headers


def test_the_abstract_dispatcher_still_declares_no_expose_headers():
    assert not hasattr(Dispatcher, "cors_expose_headers")
