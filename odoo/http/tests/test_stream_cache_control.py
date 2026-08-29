import pytest
from werkzeug.test import EnvironBuilder

from odoo.http.constants import STATIC_CACHE_LONG
from odoo.http.stream import Stream


@pytest.fixture
def payload(tmp_path):
    target = tmp_path / "file.bin"
    target.write_bytes(b"payload")
    return target


def _response(payload, **kwargs):
    """Serve a file with an explicit environ, so no request global is needed."""
    stream = Stream(
        type="path",
        path=str(payload),
        mimetype="application/octet-stream",
        download_name="file.bin",
        etag="test-etag",
        last_modified=payload.stat().st_mtime,
        size=payload.stat().st_size,
        **{k: v for k, v in kwargs.items() if k in Stream._ALLOWED_KWARGS},
    )
    call = {k: v for k, v in kwargs.items() if k not in Stream._ALLOWED_KWARGS}
    return stream.get_response(
        environ=EnvironBuilder(method="GET", path="/web/content/1").get_environ(),
        **call,
    )


def _cache_control(response):
    return response.headers.get("Cache-Control", "")


def test_a_non_public_stream_is_private_and_never_public(payload):
    """A shared proxy must not cache an attachment the user had to be
    authorised for. `public` defaults to False, so this is the default."""
    cc = _cache_control(_response(payload, max_age=3600))
    assert "private" in cc
    assert "public" not in cc


def test_a_public_stream_with_a_lifetime_is_marked_public(payload):
    cc = _cache_control(_response(payload, public=True, max_age=3600))
    assert "public" in cc


def test_a_public_stream_with_no_lifetime_is_not_marked_public(payload):
    """`public` with no max-age would invite a proxy to cache heuristically,
    which is the one thing the flag is not asking for."""
    cc = _cache_control(_response(payload, public=True))
    assert "public" not in cc


def test_a_public_stream_with_a_zero_lifetime_is_not_marked_public(payload):
    cc = _cache_control(_response(payload, public=True, max_age=0))
    assert "public" not in cc


def test_immutable_implies_the_long_lifetime_and_the_directive(payload):
    response = _response(payload, public=True, immutable=True)
    cc = _cache_control(response)
    assert "immutable" in cc
    assert f"max-age={STATIC_CACHE_LONG}" in cc


def test_nosniff_is_always_set(payload):
    for kwargs in ({}, {"public": True}, {"immutable": True}):
        response = _response(payload, **kwargs)
        assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_the_default_policy_locks_the_document_down(payload):
    response = _response(payload)
    assert response.headers["Content-Security-Policy"] == "default-src 'none'"


def test_a_none_policy_leaves_the_header_off(payload):
    """`_serve_static` passes None and lets Application.set_csp decide, which
    only adds a policy for images."""
    response = _response(payload, content_security_policy=None)
    assert "Content-Security-Policy" not in response.headers


def test_an_explicit_policy_is_used_verbatim(payload):
    response = _response(payload, content_security_policy="frame-ancestors 'self'")
    assert response.headers["Content-Security-Policy"] == "frame-ancestors 'self'"
