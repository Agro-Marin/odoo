"""DB-free unit tests for :mod:`odoo.http.request_class` helpers.

Run via ``pytest odoo/http/tests``.
"""

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
    # The catalog read is memoised within the TTL bucket; only the (cheap,
    # host-dependent) db_filter runs per call.
    assert lister.call_count == 1


def test_monodb_dblist_degrades_when_postgres_unreachable(fresh_monodb_cache):
    """PostgreSQL being down must yield "no databases" (db-less serving),
    not propagate — this runs in ``_post_init`` for every cookie-less
    request, including static assets and ``/web/login``. ``db_list`` has the
    same guard; the memoised monodb path must not lose it."""
    boom = psycopg.OperationalError("connection refused")
    with patch.object(request_class, "_list_all_dbs", side_effect=boom):
        assert request_class._monodb_dblist("h") == []

    # lru_cache does not cache the failure: once PostgreSQL is back, the
    # very next probe sees the catalog again.
    with (
        patch.object(request_class, "_list_all_dbs", return_value=["only"]),
        patch.object(
            request_class, "db_filter", side_effect=lambda dbs, host: list(dbs)
        ),
    ):
        assert request_class._monodb_dblist("h") == ["only"]
