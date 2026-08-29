import pathlib
from unittest.mock import patch

import psycopg
import pytest

import odoo.http
from odoo.http import helpers, request_class


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


def test_monodb_dblist_filters_cached_catalog(fresh_monodb_cache):
    with _catalog(["a", "b"]) as lister, _passthrough_filter():
        assert request_class._monodb_dblist("h") == ["a", "b"]
        assert request_class._monodb_dblist("h") == ["a", "b"]
    assert lister.call_count == 1


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


def test_the_catalog_is_read_once_per_ttl_bucket(fresh_monodb_cache):
    with _catalog(["a", "b"]) as lister, _passthrough_filter():
        for _ in range(5):
            assert request_class._monodb_dblist("h") == ["a", "b"]
    assert lister.call_count == 1


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


def test_the_caller_cannot_mutate_the_cached_answer(fresh_monodb_cache):
    with _catalog(["a"]), _passthrough_filter():
        first = request_class._monodb_dblist("h")
        first.append("smuggled")
        assert request_class._monodb_dblist("h") == ["a"]


def test_the_monodb_cache_is_registered_as_a_catalog_listener():
    from odoo.service.db import listing

    assert helpers.clear_db_list_cache in listing._catalog_listeners
    assert request_class.clear_monodb_cache is helpers.clear_db_list_cache


def test_a_catalog_change_expires_the_cached_list(fresh_monodb_cache):
    from odoo.service.db import listing

    with _catalog(["a"]) as lister, _passthrough_filter():
        assert request_class._monodb_dblist("h") == ["a"]
        assert request_class._monodb_dblist("h") == ["a"]
        assert lister.call_count == 1

        listing.invalidate_catalog_caches()
        assert request_class._monodb_dblist("h") == ["a"]
        assert lister.call_count == 2


def test_a_listener_that_raises_does_not_break_the_mutation():
    from odoo.service.db import listing

    def boom():
        raise RuntimeError("boom")

    listing.register_catalog_listener(boom)
    try:
        listing.invalidate_catalog_caches()
    finally:
        listing._catalog_listeners.remove(boom)
