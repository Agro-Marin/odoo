import pathlib
import types
from typing import Any
from unittest.mock import patch

import psycopg
import pytest

import odoo.http
from odoo.http import helpers, request_class
from odoo.http.request_class import Request


@pytest.fixture
def fresh_monodb_cache():
    request_class.clear_monodb_cache()
    yield
    request_class.clear_monodb_cache()


def _catalog(dbs):
    return patch.object(helpers.odoo.service.db, "list_dbs", return_value=list(dbs))


def _passthrough_filter():
    return patch.object(
        helpers, "db_filter", side_effect=lambda dbs, host=None: list(dbs)
    )


def test_monodb_dblist_filters_the_catalog(fresh_monodb_cache):
    with _catalog(["a", "b"]), _passthrough_filter():
        assert request_class._monodb_dblist("h") == ["a", "b"]
        assert request_class._monodb_dblist("h") == ["a", "b"]


def test_monodb_dblist_degrades_when_postgres_unreachable(fresh_monodb_cache):
    boom = psycopg.OperationalError("connection refused")
    with patch.object(helpers.odoo.service.db, "list_dbs", side_effect=boom):
        assert request_class._monodb_dblist("h") == []

    with _catalog(["only"]), _passthrough_filter():
        assert request_class._monodb_dblist("h") == ["only"]


def test_monodb_dblist_degrades_on_any_psycopg_error(fresh_monodb_cache):
    for exc in (
        psycopg.Error("boom"),
        psycopg.OperationalError("refused"),
        psycopg.errors.InsufficientPrivilege("denied"),
    ):
        request_class.clear_monodb_cache()
        with patch.object(helpers.odoo.service.db, "list_dbs", side_effect=exc):
            assert request_class._monodb_dblist("h") == []


def test_db_list_degrades_on_any_psycopg_error(fresh_monodb_cache):
    with patch.object(
        helpers.odoo.service.db, "list_dbs", side_effect=psycopg.Error("boom")
    ):
        assert helpers.db_list(force=True, host="h") == []


def test_resolution_goes_through_the_public_db_list(fresh_monodb_cache):
    with patch.object(odoo.http, "db_list", return_value=[]) as public:
        assert request_class._monodb_dblist("h") == []
    assert public.call_args.kwargs == {"force": True, "host": "h"}


def test_resolution_goes_through_the_public_db_filter():
    """Both seams are the public ones, and both are needed to say "no database".

    A session that already carries a ``db`` never reaches the listing at all --
    ``_get_session_and_dbname`` asks ``db_filter`` whether that database is
    still served by this host. Patching only ``db_list`` therefore simulates
    "no database" for a fresh visitor and not for a logged-in one, which is how
    ``test_http``'s ``nodb_url_open`` came to need two patches rather than one.
    """
    import odoo.http.request_class as rc

    source = pathlib.Path(rc.__file__).read_text(encoding="utf-8")
    assert "http.db_filter(" in source
    assert "\n    db_filter,\n" not in source, (
        "request_class must not bind db_filter at import time, or patching "
        "odoo.http.db_filter stops reaching the resolution path"
    )


def test_http_adds_no_second_cache_over_the_catalogue(fresh_monodb_cache):
    """Freshness is `service.db.list_dbs`'s to own, and it already memoises the
    `pg_database` scan behind a lock with its own TTL and its own invalidation.

    A second TTL cache used to sit here, keyed on `(time_bucket, force)`. It
    bought nothing and cost the honesty of `force`: `db_list(force=True)` could
    answer from up to five seconds ago, so `_serve._acquire_registry_cursor` had
    to reach past `db_list` to `service.db.list_dbs` to get the freshness the
    parameter already names.
    """
    with _catalog(["a", "b"]) as lister, _passthrough_filter():
        for _ in range(5):
            assert request_class._monodb_dblist("h") == ["a", "b"]
    assert lister.call_count == 5, "every call reaches the one cache that exists"


def test_force_reaches_list_dbs_rather_than_a_cached_answer(fresh_monodb_cache):
    with _catalog(["a"]) as lister, _passthrough_filter():
        odoo.http.db_list(force=True)
        odoo.http.db_list(force=True)

    assert [c.args for c in lister.call_args_list] == [(True,), (True,)]


def test_each_host_gets_its_own_filtered_answer(fresh_monodb_cache):
    with (
        _catalog(["a_one", "b_two"]),
        patch.object(
            helpers,
            "db_filter",
            side_effect=lambda dbs, host=None: [
                db for db in dbs if db.startswith(host)
            ],
        ),
    ):
        assert request_class._monodb_dblist("a") == ["a_one"]
        assert request_class._monodb_dblist("b") == ["b_two"]
        assert request_class._monodb_dblist("a") == ["a_one"]


def test_the_caller_cannot_mutate_what_the_next_caller_sees(fresh_monodb_cache):
    """`db_filter` builds a new list on every call, so a caller that mutates its
    answer cannot reach the catalogue behind it."""
    with _catalog(["a"]):
        first = odoo.http.db_list()
        first.append("smuggled")
        assert odoo.http.db_list() == ["a"]


def test_clear_monodb_cache_drops_the_catalogue_service_db_holds():
    """It is still the name `test_http` calls between requests; what it clears is
    now `service.db`'s catalogue rather than a second cache of this package's."""
    from odoo.service.db import listing

    assert request_class.clear_monodb_cache is helpers.clear_db_list_cache

    listing._catalogue_cache = (float("inf"), ["stale"])
    helpers.clear_db_list_cache()
    assert listing._catalogue_cache is None


def test_a_listener_that_raises_does_not_break_the_mutation():
    from odoo.service.db import listing

    def boom():
        raise RuntimeError("boom")

    listing.register_catalog_listener(boom)
    try:
        listing.invalidate_catalog_caches()
    finally:
        listing._catalog_listeners.remove(boom)


def _params_request():
    """A Request with only what the `params` property touches."""
    request = Request.__new__(Request)
    request._params = {}
    request._params_source = None
    return request


def test_params_is_an_ordinary_dict_until_a_source_is_deferred():
    request = _params_request()
    assert request.params == {}

    request.params = {"a": 1}
    assert request.params == {"a": 1}

    request.params["b"] = 2
    assert request.params == {"a": 1, "b": 2}, "mutation through the getter sticks"


def test_a_deferred_source_runs_once_on_first_read():
    request = _params_request()
    calls = []

    def source():
        calls.append(1)
        return {"from": "body"}

    request._params_source = source
    assert calls == [], "declaring a source must not read the body"

    assert request.params == {"from": "body"}
    assert request.params == {"from": "body"}
    assert calls == [1], "the body is decoded once, not once per read"


def test_assigning_params_discards_a_pending_source():
    """`http_routing._handle_error` assigns `request.params` outright; the body
    it names must win over one an earlier fallback deferred."""
    request = _params_request()
    request._params_source = lambda: {"from": "body"}
    request.params = {"from": "caller"}

    assert request.params == {"from": "caller"}


def test_the_fallback_defers_the_body_instead_of_decoding_it():
    """`base`'s `_serve_fallback` never reads `request.params`; `website`'s does.
    Decoding up front made every unmatched path pay for a body only one of them
    would look at -- measured at ~0.7ms per MB of form data, and a `FileStorage`
    wrapping the whole upload for multipart."""
    from werkzeug.exceptions import NotFound

    from odoo.http import _serve

    decoded: list[int] = []

    def _decode():
        decoded.append(1)
        return {"a": "x" * 1000}

    class _IrHttp:
        def _apply_max_upload_size(self):
            pass

        def _auth_method_public(self):
            pass

        def _serve_fallback(self):
            return None

        def _handle_error(self, exc):
            return "error-response"

    this: Any = types.SimpleNamespace(
        registry={"ir.http": _IrHttp()},
        _params={},
        _params_source=None,
        httprequest=types.SimpleNamespace(max_content_length=None, content_length=1000),
        get_http_params=_decode,
    )
    this._bound_registry = lambda: this.registry
    this._reject_oversized_body = lambda: (
        _serve._RequestServeMixin._reject_oversized_body(this)
    )

    with pytest.raises(NotFound):
        _serve._RequestServeMixin._serve_ir_http_fallback(this, NotFound())

    assert decoded == [], "a fallback that ignores params must not decode the body"
    assert this._params_source is not None, "but it stays available to one that does"
    assert this._params_source() == {"a": "x" * 1000}


@pytest.mark.parametrize(
    ("limit", "length", "refused"),
    [
        (1000, 1001, True),
        (1000, 1000, False),
        (1000, None, False),  # chunked: not caught here, and never read either
        (None, 10**9, False),  # no limit configured
    ],
)
def test_an_unmatched_path_refuses_an_oversized_body_by_its_declared_length(
    limit, length, refused
):
    """The eager parse used to raise `RequestEntityTooLarge` as a side effect, so
    deferring the body deferred the only effect `_apply_max_upload_size` had on a
    path with no endpoint. Checking the declared length is both the restored
    contract and the cheaper question."""
    from werkzeug.exceptions import RequestEntityTooLarge

    from odoo.http import _serve

    this: Any = types.SimpleNamespace(
        httprequest=types.SimpleNamespace(
            max_content_length=limit, content_length=length
        )
    )
    if refused:
        with pytest.raises(RequestEntityTooLarge):
            _serve._RequestServeMixin._reject_oversized_body(this)
    else:
        _serve._RequestServeMixin._reject_oversized_body(this)
