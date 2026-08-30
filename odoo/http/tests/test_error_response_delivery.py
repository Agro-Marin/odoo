"""What a client actually receives when a request fails.

The nodb 404 is the case worth pinning end to end. Its body is negotiated by
`_serve_nodb`, but the response only reaches the client because the exception
carries it through `Application.__call__`'s handler and werkzeug's
`HTTPException.get_response` honours `exc.response`. That last step is
third-party behaviour, and nothing else here pins it: `test_wsgi_entry`
replaces `_serve_nodb` with a marker and `test_content_negotiation` stops at
dispatcher selection.
"""

import io
from typing import Any
from unittest import mock

import pytest
import werkzeug.exceptions
import werkzeug.wrappers

from odoo.http.application import Application
from odoo.http.constants import NOT_FOUND_NODB, NOT_FOUND_NODB_TEXT
from odoo.http.dispatcher import Json2Dispatcher
from odoo.http.routing import build_routing_map
from odoo.http.session import FilesystemSessionStore, Session
from odoo.http.wrappers import Response


def _environ(path="/no-such-route", content_type=None, accept="*/*"):
    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "8069",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "HTTP_HOST": "localhost:8069",
        "HTTP_ACCEPT": accept,
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(b""),
        "wsgi.errors": io.BytesIO(),
        "wsgi.multithread": True,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
        "wsgi.version": (1, 0),
    }
    if content_type:
        environ["CONTENT_TYPE"] = content_type
        environ["CONTENT_LENGTH"] = "0"
    return environ


@pytest.fixture
def nodb_app(tmp_path):
    """An Application with an empty routing map and no database: every path 404s."""
    app = Application()
    app.__dict__["nodb_routing_map"] = build_routing_map([])
    app.__dict__["session_store"] = FilesystemSessionStore(
        str(tmp_path), session_class=Session, renew_missing=True
    )
    return app


def _serve(app, environ):
    captured: dict[str, Any] = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = {k.lower(): v for k, v in headers}

    with (
        mock.patch("odoo.http.helpers.db_list", return_value=[]),
        mock.patch("odoo.http.request_class._monodb_dblist", return_value=[]),
    ):
        body = b"".join(app(environ, start_response))
    return captured["status"], captured["headers"], body


def test_a_browser_gets_the_nodb_not_found_page(nodb_app):
    status, headers, body = _serve(nodb_app, _environ(accept="text/html"))

    assert status.startswith("404")
    assert headers["content-type"].startswith("text/html")
    assert NOT_FOUND_NODB.encode() in body


def test_a_json_client_gets_the_nodb_message_as_json(nodb_app):
    status, headers, body = _serve(nodb_app, _environ(content_type="application/json"))

    assert status.startswith("404")
    assert headers["content-type"].startswith("application/json")
    assert NOT_FOUND_NODB_TEXT.encode() in body
    assert b"<!DOCTYPE html>" not in body


def test_json2_error_responses_are_the_package_response_type():
    """`handle_error` is annotated `-> Response`; an HTTPException carrying a
    bare werkzeug response used to be handed back unwrapped, and survived only
    because `post_dispatch` happens to touch nothing but `.headers`."""
    exc = werkzeug.exceptions.NotFound()
    exc.response = werkzeug.wrappers.Response(b"raw", status=404)
    dispatcher = Json2Dispatcher.__new__(Json2Dispatcher)
    dispatcher.request = None

    assert isinstance(dispatcher.handle_error(exc), Response)


def test_the_negotiated_nodb_404_is_the_one_that_reaches_the_client(nodb_app):
    """`_serve_nodb` builds the body and `Application` delivers it -- once.

    The two carry an error response on different attributes: werkzeug's
    `exc.response`, which `HTTPException.get_response` honours, and Odoo's
    `error_response`, which is what `_ensure_error_response` reads. Writing the
    werkzeug one left the odoo one empty, so the entrypoint asked the
    dispatcher for a second response and delivered that instead.
    `Json2Dispatcher.handle_error` short-circuits on `exc.response` and paid
    only a rewrap; `JsonRPCDispatcher.handle_error` has no such branch and
    serialized the exception twice for every 404 a JSON-RPC client sent.
    """
    from odoo.http.dispatcher import JsonRPCDispatcher

    calls = []
    original = JsonRPCDispatcher.handle_error

    def counted(self, exc):
        calls.append(exc)
        return original(self, exc)

    with mock.patch.object(JsonRPCDispatcher, "handle_error", counted):
        status, headers, body = _serve(
            nodb_app, _environ(content_type="application/json-rpc")
        )

    assert len(calls) == 1
    assert headers["content-type"].startswith("application/json")
    assert NOT_FOUND_NODB_TEXT.encode() in body
    assert status.startswith("200"), "a JSON-RPC fault is a 200 with an error member"
