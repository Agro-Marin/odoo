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
