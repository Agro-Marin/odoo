import io
from unittest import mock

import pytest

from odoo.http import application
from odoo.http.core import _request_stack
from odoo.http.exceptions import RegistryError


def _environ(path="/x", method="GET"):
    return {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "8069",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "HTTP_HOST": "localhost:8069",
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(b""),
        "wsgi.errors": io.BytesIO(),
        "wsgi.multithread": True,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
        "wsgi.version": (1, 0),
    }


class _FakeRequest:
    """Enough of Request for __call__'s decisions; each serve_* is a marker."""

    def __init__(self, httprequest, app, db=None, serve=None):
        self.httprequest = httprequest
        self.app = app
        self.db = db
        self.dispatcher = mock.Mock()
        self.dispatcher.serializes_errors_in_dev_mode = False
        # what HttpDispatcher.handle_error does with an HTTPException
        self.dispatcher.handle_error.side_effect = lambda exc: exc
        self._post_init_done = False
        self.session = mock.Mock()
        self.calls: list[str] = []
        self._serve = serve or (lambda name: f"served:{name}")

    def _post_init(self):
        self._post_init_done = True

    def _get_profiler_context_manager(self):
        import contextlib

        return contextlib.nullcontext()

    def _serve_db(self):
        self.calls.append("db")
        return self._serve("db")

    def _serve_nodb(self):
        self.calls.append("nodb")
        return self._serve("nodb")

    def _serve_static(self, filepath):
        self.calls.append("static")
        return self._serve("static")


def _run(app, environ, request):
    """Drive __call__ with a prepared request and collect the WSGI status."""
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status

    def _response(env, sr):
        sr("200 OK", [])
        return [b"body"]

    request._serve = lambda name: (captured.setdefault("served", name), _response)[1]
    with mock.patch.object(application, "Request", lambda hr, app: request):
        body = app(environ, start_response)
    captured["body"] = b"".join(body)
    return captured


@pytest.fixture(autouse=True)
def _stack_is_left_empty():
    yield
    assert _request_stack.top is None, "__call__ leaked a request on the stack"


def test_a_request_with_a_database_is_served_by_serve_db():
    app = application.Application()
    hr = None
    req = _FakeRequest(hr, app, db="db")
    with mock.patch.object(app, "get_static_file", return_value=None):
        out = _run(app, _environ(), req)
    assert req.calls == ["db"] and out["served"] == "db"


def test_a_request_without_a_database_is_served_by_serve_nodb():
    app = application.Application()
    req = _FakeRequest(None, app, db=None)
    with mock.patch.object(app, "get_static_file", return_value=None):
        _run(app, _environ(), req)
    assert req.calls == ["nodb"]


def test_a_static_path_never_reaches_the_router():
    app = application.Application()
    req = _FakeRequest(None, app, db="db")
    with (
        mock.patch.object(app, "get_static_file", return_value="/tmp/asset.js"),
        mock.patch.object(app, "_serve_static_file") as served,
    ):
        served.return_value = lambda env, sr: (sr("200 OK", []), [b""])[1]
        _run(app, _environ("/web/static/asset.js"), req)
    assert req.calls == [], "the database was consulted for a static file"
    served.assert_called_once()


def test_trace_is_refused_before_anything_else_runs():
    """TRACE is how cross-site tracing reads headers the script cannot; it is
    refused for every path, database or not."""
    app = application.Application()
    req = _FakeRequest(None, app, db="db")
    with mock.patch.object(app, "get_static_file") as static:
        out = _run(app, _environ(method="TRACE"), req)
    assert out["status"].startswith("405")
    assert req.calls == []
    static.assert_not_called()


def test_a_nul_in_the_path_is_a_404_and_never_reaches_the_resolver():
    app = application.Application()
    req = _FakeRequest(None, app, db="db")
    with mock.patch.object(app, "get_static_file") as static:
        out = _run(app, _environ("/web/static/\x00.js"), req)
    assert out["status"].startswith("404")
    static.assert_not_called(), "get_static_file must not be handed a NUL path"


def test_a_registry_error_falls_back_to_serving_without_a_database():
    app = application.Application()
    req = _FakeRequest(None, app, db="db")

    def boom():
        req.calls.append("db")
        raise RegistryError("registry is unusable")

    req._serve_db = boom
    with (
        mock.patch.object(app, "get_static_file", return_value=None),
        mock.patch.object(app, "_recover_from_registry_error") as recover,
    ):
        recover.return_value = lambda env, sr: (sr("200 OK", []), [b""])[1]
        _run(app, _environ(), req)
    assert req.calls == ["db"]
    recover.assert_called_once()


def test_a_failure_still_answers_and_empties_the_stack():
    app = application.Application()
    req = _FakeRequest(None, app, db="db")
    req._serve_db = mock.Mock(side_effect=ValueError("boom"))
    req.dispatcher.handle_error.side_effect = RuntimeError("and the handler too")
    req.dispatcher.post_dispatch.side_effect = None

    with mock.patch.object(app, "get_static_file", return_value=None):
        out = _run(app, _environ(), req)
    assert out["status"].startswith("500")


def test_a_rerouted_request_has_its_second_httprequest_closed():
    """__call__ owns only the one the context manager made; a reroute creates a
    second, and leaking it leaks the parsed body with it."""
    app = application.Application()
    req = _FakeRequest(None, app, db=None)
    rerouted = mock.Mock()

    def serve_nodb():
        req.httprequest = rerouted
        return lambda env, sr: (sr("200 OK", []), [b""])[1]

    req._serve_nodb = serve_nodb
    with mock.patch.object(app, "get_static_file", return_value=None):
        _run(app, _environ(), req)
    rerouted.close.assert_called_once()


def test_a_memoised_singleton_shadows_a_class_level_replacement():
    """`_locked_cached_property` memoises into `instance.__dict__`, so patching
    `Application.session_store` on the CLASS -- what `test_http`'s setUpClass
    does for the session store and both geoip readers -- is a no-op on a `root`
    that has already served a request. `odoo.libs.func.reset_cached_properties`
    is what makes that patch land, and it can only do so while the class
    attribute is still the descriptor: called AFTER the patch it no longer
    recognises the name and clears nothing. The reset has to come first, and
    nothing but this test says so.
    """
    from odoo.libs.func import reset_cached_properties

    app = application.Application()
    app.__dict__["session_store"] = "memoised"

    with mock.patch.object(application.Application, "session_store", "patched"):
        assert app.session_store == "memoised"
        reset_cached_properties(app)
        assert app.session_store == "memoised", (
            "reset after the patch clears nothing: the name no longer resolves "
            "to a cached_property, so reset_cached_properties skips it"
        )

    reset_cached_properties(app)
    assert "session_store" not in app.__dict__, "reset first, patch second"
