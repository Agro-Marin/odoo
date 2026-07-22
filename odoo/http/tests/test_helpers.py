"""DB-free unit tests for pure helpers in :mod:`odoo.http.helpers`.

Run via ``pytest odoo/http/tests``.
"""

import threading
import types

from odoo.http.helpers import (
    _normalize_dbfilter_host,
    _restore_thread_attr,
    content_disposition,
    is_cors_preflight,
)


def test_content_disposition_encodes_unicode_and_quotes():
    header = content_disposition('résumé "x".pdf')
    assert header.startswith("attachment; filename*=UTF-8''")
    assert "r%C3%A9sum%C3%A9" in header
    assert '"' not in header  # quote(safe='') percent-encodes it


def test_content_disposition_inline():
    assert content_disposition("a.pdf", "inline").startswith("inline; ")


def test_content_disposition_rejects_bad_type():
    import pytest

    with pytest.raises(ValueError, match="Invalid disposition_type"):
        content_disposition("a.pdf", "bogus")


def test_normalize_dbfilter_host_strips_port_www_and_lowercases():
    assert _normalize_dbfilter_host("WWW.Example.COM:8069") == "example.com"
    assert _normalize_dbfilter_host("example.com") == "example.com"
    assert _normalize_dbfilter_host("WWW.sub.example.com") == "sub.example.com"


def _fake_request(method):
    env = {"REQUEST_METHOD": method}
    httprequest = types.SimpleNamespace(method=method, environ=env)
    return types.SimpleNamespace(httprequest=httprequest)


def test_is_cors_preflight_returns_real_bool():
    """Regression: with a cors allow-origin string set, the helper used to leak
    that string instead of a bool despite its ``-> bool`` contract."""
    endpoint = types.SimpleNamespace(routing={"cors": "https://example.com"})
    result = is_cors_preflight(_fake_request("OPTIONS"), endpoint)
    assert result is True
    # non-OPTIONS -> False; no cors -> False
    assert is_cors_preflight(_fake_request("GET"), endpoint) is False
    no_cors = types.SimpleNamespace(routing={})
    assert is_cors_preflight(_fake_request("OPTIONS"), no_cors) is False


def test_restore_thread_attr_deletes_when_absent():
    sentinel = object()
    t = threading.current_thread()
    if hasattr(t, "_probe_attr"):
        del t._probe_attr
    # absent before -> restored to absent
    _restore_thread_attr(t, "_probe_attr", sentinel, sentinel)
    assert not hasattr(t, "_probe_attr")
    # present before -> restored to value
    _restore_thread_attr(t, "_probe_attr", 42, sentinel)
    assert t._probe_attr == 42
    del t._probe_attr
