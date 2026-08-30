from unittest.mock import patch

import pytest

from odoo.service.db import listing


@pytest.fixture(autouse=True)
def fresh():
    listing._forget_catalogue()
    yield
    listing._forget_catalogue()


@pytest.fixture
def cfg():
    return {"list_db": True, "dbfilter": ".*", "db_name": [], "db_template": "tpl"}


class TestTheCatalogueScanIsShared:
    def test_repeated_calls_hit_postgres_once(self, cfg):
        with (
            patch.object(listing.odoo.tools, "config", cfg),
            patch.object(listing, "_query_catalogue", return_value=["a", "b"]) as q,
        ):
            for _ in range(10):
                assert listing.list_dbs(True) == ["a", "b"]
        assert q.call_count == 1, (
            "the pg_database scan costs ~4.7ms and sits on the db_exist RPC "
            "every client makes on connect"
        )

    def test_the_caller_cannot_poison_the_cache(self, cfg):
        with (
            patch.object(listing.odoo.tools, "config", cfg),
            patch.object(listing, "_query_catalogue", return_value=["a"]),
        ):
            first = listing.list_dbs(True)
            first.append("injected")
            assert listing.list_dbs(True) == ["a"]

    def test_a_catalogue_change_by_this_process_is_seen_at_once(self, cfg):
        with (
            patch.object(listing.odoo.tools, "config", cfg),
            patch.object(listing, "_query_catalogue", side_effect=[["a"], ["a", "b"]]),
        ):
            assert listing.list_dbs(True) == ["a"]
            listing.invalidate_catalog_caches()
            assert listing.list_dbs(True) == ["a", "b"]

    def test_the_cache_is_dropped_before_the_listeners_run(self, cfg):
        seen = []

        def listener():
            seen.append(listing._catalogue_cache)

        with (
            patch.object(listing.odoo.tools, "config", cfg),
            patch.object(listing, "_catalog_listeners", [listener]),
            patch.object(listing, "_query_catalogue", return_value=["a"]),
        ):
            listing.list_dbs(True)
            listing.invalidate_catalog_caches()
        assert seen == [None], (
            "a listener that re-reads the catalogue would repopulate it with "
            "the rows the invalidation exists to discard"
        )

    def test_the_ttl_expires(self, cfg, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr(listing.time, "monotonic", lambda: clock[0])
        with (
            patch.object(listing.odoo.tools, "config", cfg),
            patch.object(listing, "_query_catalogue", side_effect=[["a"], ["b"]]) as q,
        ):
            assert listing.list_dbs(True) == ["a"]
            clock[0] += listing.CATALOGUE_CACHE_TTL_S + 0.01
            assert listing.list_dbs(True) == ["b"]
        assert q.call_count == 2

    def test_a_zero_ttl_disables_it(self, cfg, monkeypatch):
        monkeypatch.setenv("ODOO_DB_CATALOGUE_CACHE_TTL", "0")
        with (
            patch.object(listing.odoo.tools, "config", cfg),
            patch.object(listing, "_query_catalogue", return_value=["a"]) as q,
        ):
            listing.list_dbs(True)
            listing.list_dbs(True)
        assert q.call_count == 2

    def test_the_configured_list_shortcut_never_touches_postgres(self):
        cfg = {"list_db": True, "dbfilter": "", "db_name": ["b", "a"]}
        with (
            patch.object(listing.odoo.tools, "config", cfg),
            patch.object(listing, "_query_catalogue") as q,
        ):
            assert listing.list_dbs(True) == ["a", "b"]
        q.assert_not_called()

    def test_a_failed_scan_is_not_cached(self, cfg):
        with (
            patch.object(listing.odoo.tools, "config", cfg),
            patch.object(listing, "_query_catalogue", side_effect=[None, ["a"]]) as q,
        ):
            assert listing.list_dbs(True) == [], (
                "the database selector renders at auth=none; a scan failure "
                "must answer empty rather than raise"
            )
            assert listing.list_dbs(True) == ["a"], (
                "one transient PostgreSQL hiccup blanked the database list for "
                "the whole TTL"
            )
        assert q.call_count == 2

    def test_list_db_false_is_still_refused_without_force(self, cfg):
        cfg["list_db"] = False
        with (
            patch.object(listing.odoo.tools, "config", cfg),
            patch.object(listing, "_query_catalogue", return_value=["a"]),
            pytest.raises(listing.odoo.exceptions.AccessDenied),
        ):
            listing.list_dbs()


class TestAnInvalidationCannotBeOutrunByAQueryInFlight:
    """`_query_catalogue` runs outside the lock, so a create/drop can land mid-scan.

    The scan is ~4.7ms of round trip during which `_create_empty_database`,
    `_drop_database`, `_rename_database` and `_duplicate_database` all call
    `invalidate_catalog_caches`.  Storing the scan's result unconditionally
    undoes that invalidation and serves the pre-change list for a full TTL --
    long enough for `check_db_exposed` to refuse a dump of a database that was
    just created, and to admit one that was just dropped.
    """

    def test_a_creation_during_the_scan_is_not_undone_by_it(self, cfg):
        stale = ["alpha"]

        def slow_scan():
            answer = list(stale)  # PostgreSQL answered here, pre-create
            listing.invalidate_catalog_caches()  # ...and the create lands now
            return answer

        with (
            patch.object(listing.odoo.tools, "config", cfg),
            patch.object(listing, "_query_catalogue", side_effect=slow_scan) as q,
        ):
            assert listing.list_dbs(True) == ["alpha"]
            stale = ["alpha", "beta"]
            assert listing.list_dbs(True) == ["alpha", "beta"], (
                "the outrun scan cached its pre-create list, so the new "
                "database stayed invisible for the whole TTL"
            )
        assert q.call_count == 2

    def test_an_unoutrun_scan_still_caches(self, cfg):
        with (
            patch.object(listing.odoo.tools, "config", cfg),
            patch.object(listing, "_query_catalogue", return_value=["a"]) as q,
        ):
            assert listing.list_dbs(True) == ["a"]
            assert listing.list_dbs(True) == ["a"]
        assert q.call_count == 1, "the generation guard disabled the cache"
