import types
from typing import Any

import pytest
from werkzeug.exceptions import UnsupportedMediaType

from odoo.http import _serve
from odoo.http.dispatcher import HttpDispatcher, Json2Dispatcher, JsonRPCDispatcher


def _rule(route_type, routes=("/r",), cors=None):
    routing = {"type": route_type, "routes": list(routes)}
    if cors is not None:
        routing["cors"] = cors
    return types.SimpleNamespace(endpoint=types.SimpleNamespace(routing=routing))


def _set(route_type, *, mimetype="", method="POST", content_length=1, cors=None):
    this: Any = types.SimpleNamespace(
        httprequest=types.SimpleNamespace(
            mimetype=mimetype, method=method, content_length=content_length
        ),
        dispatcher=None,
    )
    _serve._RequestServeMixin._update_dispatcher(this, _rule(route_type, cors=cors))
    return this.dispatcher


def test_an_http_route_accepts_anything():
    for mimetype in ("", "application/json", "multipart/form-data", "text/plain"):
        assert isinstance(_set("http", mimetype=mimetype), HttpDispatcher)


def test_a_jsonrpc_route_requires_a_json_content_type():
    assert isinstance(_set("jsonrpc", mimetype="application/json"), JsonRPCDispatcher)
    assert isinstance(
        _set("jsonrpc", mimetype="application/json-rpc"), JsonRPCDispatcher
    )
    with pytest.raises(UnsupportedMediaType):
        _set("jsonrpc", mimetype="application/x-www-form-urlencoded")


def test_a_json2_route_also_accepts_a_request_with_no_body():
    assert isinstance(_set("json2", mimetype="application/json"), Json2Dispatcher)
    assert isinstance(
        _set("json2", mimetype="", method="GET", content_length=0), Json2Dispatcher
    )
    with pytest.raises(UnsupportedMediaType):
        _set("json2", mimetype="text/plain", content_length=99)


def test_the_415_names_the_types_the_route_does_accept():
    with pytest.raises(UnsupportedMediaType) as caught:
        _set("jsonrpc", mimetype="text/plain")

    response = caught.value.response
    assert response.status_code == 415
    accept = response.headers["Accept"]
    for mimetype in JsonRPCDispatcher.mimetypes:
        assert mimetype in accept, accept


def test_the_415_body_names_the_route_and_both_sides_of_the_mismatch():
    with pytest.raises(UnsupportedMediaType) as caught:
        _set("jsonrpc", mimetype="text/plain")
    body = caught.value.response.get_data(as_text=True)
    assert "/r" in body
    assert "jsonrpc" in body
    assert "http" in body, "the types the request IS compatible with"


def test_a_cors_preflight_is_exempt_from_the_check():
    dispatcher = _set("jsonrpc", mimetype="", method="OPTIONS", cors="*")
    assert isinstance(dispatcher, JsonRPCDispatcher)


def test_an_options_request_without_cors_is_not_exempt():
    with pytest.raises(UnsupportedMediaType):
        _set("jsonrpc", mimetype="", method="OPTIONS")
