import contextlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from werkzeug.test import EnvironBuilder

from odoo.http.stream import Stream
from odoo.tools import config


@pytest.fixture
def filestore(tmp_path):
    store = tmp_path / "filestore"
    store.mkdir()
    target = store / "ab" / "abcdef0123456789"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"payload")
    return tmp_path, target


def _stream_for(path):
    stream = Stream(type="path", path=str(path), mimetype="application/octet-stream")
    stream.size = path.stat().st_size
    stream.last_modified = path.stat().st_mtime
    stream.etag = "test-etag"
    stream.download_name = "file.bin"
    return stream


@contextlib.contextmanager
def _serving(tmp_path, *, x_sendfile):
    environ = EnvironBuilder(method="GET", path="/web/content/1").get_environ()
    environ["werkzeug.request"] = None
    fake_request = SimpleNamespace(httprequest=SimpleNamespace(environ=environ))
    with (
        _config(tmp_path, x_sendfile=x_sendfile),
        patch("odoo.http.stream.request", fake_request),
    ):
        yield


@contextlib.contextmanager
def _config(tmp_path, *, x_sendfile):
    config["x_sendfile"] = x_sendfile
    config["data_dir"] = str(tmp_path)
    try:
        yield
    finally:
        config.pop("x_sendfile", None)
        config.pop("data_dir", None)


def test_x_sendfile_is_removed_when_x_accel_redirect_is_added(filestore):
    tmp_path, target = filestore
    stream = _stream_for(target)
    with _serving(tmp_path, x_sendfile=True):
        res = stream.get_response(as_attachment=False)

    if "X-Accel-Redirect" not in res.headers:
        pytest.skip("werkzeug did not take the x-sendfile path in this environment")

    assert "X-Sendfile" not in res.headers, (
        "X-Sendfile still present alongside X-Accel-Redirect: it carries the "
        f"absolute filestore path ({res.headers.get('X-Sendfile')!r}) and nginx "
        "passes unknown upstream headers through, disclosing data_dir."
    )


def test_x_accel_redirect_is_relative_to_the_filestore_not_absolute(filestore):
    tmp_path, target = filestore
    stream = _stream_for(target)
    with _serving(tmp_path, x_sendfile=True):
        res = stream.get_response(as_attachment=False)

    redirect = res.headers.get("X-Accel-Redirect")
    if redirect is None:
        pytest.skip("werkzeug did not take the x-sendfile path in this environment")
    assert redirect.startswith("/web/filestore/")
    assert str(tmp_path) not in redirect, (
        "X-Accel-Redirect must be the nginx-internal location, never an "
        "absolute server path"
    )


def test_no_absolute_server_path_leaks_in_any_response_header(filestore):
    tmp_path, target = filestore
    stream = _stream_for(target)
    with _serving(tmp_path, x_sendfile=True):
        res = stream.get_response(as_attachment=False)

    leaked = {
        name: value
        for name, value in res.headers.items()
        if str(tmp_path) in str(value)
    }
    assert not leaked, f"headers disclosing the server filesystem: {leaked}"


def test_x_sendfile_disabled_leaves_no_accel_redirect(filestore):
    tmp_path, target = filestore
    stream = _stream_for(target)
    with _serving(tmp_path, x_sendfile=False):
        res = stream.get_response(as_attachment=False)
    assert "X-Accel-Redirect" not in res.headers


def test_a_path_outside_the_filestore_gets_no_accel_redirect(filestore):
    tmp_path, _ = filestore
    with tempfile.TemporaryDirectory() as outside:
        target = Path(outside) / "elsewhere.bin"
        target.write_bytes(b"payload")
        stream = _stream_for(target)
        with _serving(tmp_path, x_sendfile=True):
            res = stream.get_response(as_attachment=False)
        assert "X-Accel-Redirect" not in res.headers


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
