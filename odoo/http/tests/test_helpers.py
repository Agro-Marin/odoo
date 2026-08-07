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
    assert '"' not in header


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


def test_dbfilter_host_normalized_exactly_once():
    from odoo.http.helpers import _compiled_dbfilter, db_filter
    from odoo.tools import config

    saved = config["dbfilter"]
    config["dbfilter"] = "^%h$"
    _compiled_dbfilter.cache_clear()
    try:
        assert db_filter(["www.example.com"], host="www.www.example.com") == [
            "www.example.com"
        ]
        assert db_filter(["example.com"], host="www.www.example.com") == []
    finally:
        config["dbfilter"] = saved
        _compiled_dbfilter.cache_clear()


def _fake_request(method):
    env = {"REQUEST_METHOD": method}
    httprequest = types.SimpleNamespace(method=method, environ=env)
    return types.SimpleNamespace(httprequest=httprequest)


def test_is_cors_preflight_returns_real_bool():
    endpoint = types.SimpleNamespace(routing={"cors": "https://example.com"})
    result = is_cors_preflight(_fake_request("OPTIONS"), endpoint)
    assert result is True
    assert is_cors_preflight(_fake_request("GET"), endpoint) is False
    no_cors = types.SimpleNamespace(routing={})
    assert is_cors_preflight(_fake_request("OPTIONS"), no_cors) is False


def test_db_filter_without_request_uses_empty_host():
    from odoo.http.helpers import db_filter
    from odoo.tools import config

    saved = config["dbfilter"]
    config["dbfilter"] = "^%d$"
    try:
        assert db_filter(["somedb"]) == []
    finally:
        config["dbfilter"] = saved


def test_restore_thread_attr_deletes_when_absent():
    sentinel = object()
    t = threading.current_thread()
    if hasattr(t, "_probe_attr"):
        del t._probe_attr
    _restore_thread_attr(t, "_probe_attr", sentinel, sentinel)
    assert not hasattr(t, "_probe_attr")
    _restore_thread_attr(t, "_probe_attr", 42, sentinel)
    assert t._probe_attr == 42
    del t._probe_attr


def test_normalize_dbfilter_host_ipv6_keeps_brackets():
    assert _normalize_dbfilter_host("[::1]:8069") == "[::1]"
    assert _normalize_dbfilter_host("[2001:DB8::1]") == "[2001:db8::1]"
    assert _normalize_dbfilter_host("[::1") == "[::1"


def test_serialize_exception_masks_infra_errors_for_clients_only():
    import psycopg

    from odoo.http import _request_stack
    from odoo.http.helpers import serialize_exception

    secret_os = OSError("/srv/filestore/prod/.session/secret-layout")
    secret_pg = psycopg.OperationalError("UPDATE res_users SET password=...")

    assert "filestore" in serialize_exception(secret_os)["message"]
    assert "res_users" in serialize_exception(secret_pg)["message"]

    _request_stack.push(types.SimpleNamespace())
    try:
        for exc in (secret_os, secret_pg):
            data = serialize_exception(exc)
            assert data["message"] == "Internal Server Error"
            assert data["arguments"] == ()
            assert data["name"].endswith(type(exc).__name__)
        assert serialize_exception(ValueError("bad domain"))["message"] == "bad domain"
    finally:
        _request_stack.pop()
