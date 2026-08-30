import io
import types
from typing import Any

from odoo.http._response import _RequestResponseMixin
from odoo.http.wrappers import HTTPRequest

BODY = b"a=1&b=2"


def _httprequest(body=BODY, query="db=gone&keep=1", path="/old"):
    return HTTPRequest(
        {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "SERVER_NAME": "localhost",
            "SERVER_PORT": "8069",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "HTTP_HOST": "localhost:8069",
            "wsgi.url_scheme": "http",
            "CONTENT_TYPE": "application/x-www-form-urlencoded",
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": io.BytesIO(body),
            "wsgi.errors": io.BytesIO(),
            "wsgi.multithread": True,
            "wsgi.multiprocess": False,
            "wsgi.run_once": False,
            "wsgi.version": (1, 0),
        }
    )


def _reroute(httprequest, path, query=None):
    this: Any = types.SimpleNamespace(httprequest=httprequest)
    _RequestResponseMixin.reroute(this, path, query)
    return this.httprequest


def test_the_path_and_query_are_replaced():
    new = _reroute(_httprequest(), "/new", "keep=1")
    assert new.path == "/new"
    assert new.query_string == b"keep=1"


def test_an_omitted_query_keeps_the_original_one():
    new = _reroute(_httprequest(query="a=1"), "/new")
    assert new.query_string == b"a=1"


def test_raw_uri_is_rebuilt_and_drops_the_question_mark_when_empty():
    assert _reroute(_httprequest(), "/new", "k=1").raw_environ["RAW_URI"] == "/new?k=1"
    assert _reroute(_httprequest(), "/new", "").raw_environ["RAW_URI"] == "/new"


def test_a_body_already_parsed_survives_the_reroute():
    original = _httprequest()
    assert dict(original.form) == {"a": "1", "b": "2"}, "read it first"

    new = _reroute(original, "/new", "keep=1")
    assert dict(new.form) == {"a": "1", "b": "2"}


def test_a_body_not_yet_parsed_is_still_readable_afterwards():
    new = _reroute(_httprequest(), "/new", "keep=1")
    assert dict(new.form) == {"a": "1", "b": "2"}


def test_the_reroute_produces_a_new_object_so_the_old_one_can_be_closed():
    original = _httprequest()
    assert _reroute(original, "/new") is not original


def test_a_bytes_path_is_accepted():
    assert _reroute(_httprequest(), b"/new").path == "/new"
