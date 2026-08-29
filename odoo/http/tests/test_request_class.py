from unittest.mock import patch

import psycopg
import pytest

from odoo.http import request_class


@pytest.fixture
def fresh_monodb_cache():
    request_class.clear_monodb_cache()
    yield
    request_class.clear_monodb_cache()


def test_monodb_dblist_filters_cached_catalog(fresh_monodb_cache):
    with (
        patch.object(request_class, "_list_all_dbs", return_value=["a", "b"]) as lister,
        patch.object(
            request_class, "db_filter", side_effect=lambda dbs, host: list(dbs)
        ),
    ):
        assert request_class._monodb_dblist("h") == ["a", "b"]
        assert request_class._monodb_dblist("h") == ["a", "b"]
    assert lister.call_count == 1


def test_monodb_dblist_degrades_when_postgres_unreachable(fresh_monodb_cache):
    boom = psycopg.OperationalError("connection refused")
    with patch.object(request_class, "_list_all_dbs", side_effect=boom):
        assert request_class._monodb_dblist("h") == []

    with (
        patch.object(request_class, "_list_all_dbs", return_value=["only"]),
        patch.object(
            request_class, "db_filter", side_effect=lambda dbs, host: list(dbs)
        ),
    ):
        assert request_class._monodb_dblist("h") == ["only"]


def test_monodb_dblist_degrades_on_any_psycopg_error(fresh_monodb_cache):
    for exc in (
        psycopg.Error("boom"),
        psycopg.OperationalError("refused"),
        psycopg.errors.InsufficientPrivilege("denied"),
    ):
        request_class.clear_monodb_cache()
        with patch.object(request_class, "_list_all_dbs", side_effect=exc):
            assert request_class._monodb_dblist("h") == []


def test_db_list_degrades_on_any_psycopg_error():
    from odoo.http import helpers

    with patch.object(
        helpers.odoo.service.db, "list_dbs", side_effect=psycopg.Error("boom")
    ):
        assert helpers.db_list(force=True, host="h") == []


def test_monodb_dblist_caches_the_filtering_not_only_the_catalog(fresh_monodb_cache):
    with (
        patch.object(request_class, "_list_all_dbs", return_value=["a", "b"]),
        patch.object(
            request_class, "db_filter", side_effect=lambda dbs, host: list(dbs)
        ) as filterer,
    ):
        for _ in range(5):
            assert request_class._monodb_dblist("h") == ["a", "b"]
    assert filterer.call_count == 1


def test_each_host_gets_its_own_filtered_answer(fresh_monodb_cache):
    with (
        patch.object(request_class, "_list_all_dbs", return_value=["a_one", "b_two"]),
        patch.object(
            request_class,
            "db_filter",
            side_effect=lambda dbs, host: [db for db in dbs if db.startswith(host)],
        ),
    ):
        assert request_class._monodb_dblist("a") == ["a_one"]
        assert request_class._monodb_dblist("b") == ["b_two"]
        assert request_class._monodb_dblist("a") == ["a_one"]


def test_the_caller_cannot_mutate_the_cached_answer(fresh_monodb_cache):
    with (
        patch.object(request_class, "_list_all_dbs", return_value=["a"]),
        patch.object(
            request_class, "db_filter", side_effect=lambda dbs, host: list(dbs)
        ),
    ):
        first = request_class._monodb_dblist("h")
        first.append("smuggled")
        assert request_class._monodb_dblist("h") == ["a"]


def test_the_monodb_cache_is_registered_as_a_catalog_listener():
    from odoo.service.db import listing

    assert request_class.clear_monodb_cache in listing._catalog_listeners


def test_a_catalog_change_expires_the_cached_list(fresh_monodb_cache):
    from odoo.service.db import listing

    with (
        patch.object(request_class, "_list_all_dbs", return_value=["a"]) as lister,
        patch.object(
            request_class, "db_filter", side_effect=lambda dbs, host: list(dbs)
        ),
    ):
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
