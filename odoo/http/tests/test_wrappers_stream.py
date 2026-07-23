"""DB-free regression tests for Response construction and Stream.read().

Run via ``pytest odoo/http/tests``.
"""

import pytest
import werkzeug.wrappers

from odoo.http.stream import Stream
from odoo.http.wrappers import Response, _Response


def test_response_load_always_returns_facade():
    """Regression: loading a plain werkzeug Response returned a raw
    ``_Response``, which fails ``isinstance(x, Response)`` facade checks
    (ProxyMeta has no ``__instancecheck__``) — e.g. ``Json2Dispatcher``'s
    pass-through-vs-serialize decision."""
    raw = werkzeug.wrappers.Response("hi", status=201)
    loaded = Response.load(raw)
    assert isinstance(loaded, Response)
    assert loaded.status_code == 201
    for result in ("txt", b"bytes", None):
        assert isinstance(Response.load(result), Response)
    # a facade passes through unchanged
    facade = Response("x", status=202)
    assert Response.load(facade) is facade


def test_response_ctor_from_werkzeug_response_is_not_double_wrapped():
    r = Response(werkzeug.wrappers.Response("hi", status=203))
    assert type(r._wrapped__) is _Response  # not a nested facade
    assert r.status_code == 203


def test_response_wrapping_rejects_dropped_kwargs():
    """Regression: ``Response(existing, status=404)`` silently kept status 200."""
    base = Response("hi", status=200)
    with pytest.raises(TypeError, match="ignores keyword arguments"):
        Response(base, status=404)
    with pytest.raises(TypeError, match="ignores keyword arguments"):
        Response(_Response("hi"), headers=[("X", "1")])


def test_response_plain_wrapping_still_works():
    assert Response(_Response("hi", status=201)).status_code == 201
    assert Response(Response("hi", status=202)).status_code == 202


def test_response_normal_construction():
    r = Response("body", status=418, headers=[("X-A", "1")])
    assert r.status_code == 418
    assert r.headers.get("X-A") == "1"


def test_stream_read_missing_path_raises_value_error():
    """Regression: ``type='path'`` with ``path=None`` raised TypeError, not the
    documented ValueError."""
    with pytest.raises(ValueError, match="missing 'path'"):
        Stream(type="path").read()


def test_stream_read_missing_data_raises_value_error():
    with pytest.raises(ValueError, match="missing 'data'"):
        Stream(type="data").read()


def test_stream_read_url_raises_value_error():
    with pytest.raises(ValueError, match="Cannot read an URL"):
        Stream(type="url", url="http://x").read()


def test_stream_read_path_roundtrip(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"payload")
    assert Stream(type="path", path=str(p)).read() == b"payload"


def test_stream_rejects_unknown_kwargs():
    with pytest.raises(TypeError, match="unexpected keyword"):
        Stream(as_attatchment=True)  # typo


def test_stream_read_data_roundtrip():
    assert Stream(type="data", data=b"abc").read() == b"abc"
