"""DB-free regression tests for Response construction and Stream.read().

Run via ``pytest odoo/http/tests``.
"""

import pytest

from odoo.http.stream import Stream
from odoo.http.wrappers import Response, _Response


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
