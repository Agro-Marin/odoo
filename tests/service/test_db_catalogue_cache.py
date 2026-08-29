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
