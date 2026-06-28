from datetime import UTC, datetime
from unittest.mock import patch

from werkzeug.datastructures import ResponseCacheControl
from werkzeug.http import parse_cache_control_header

import odoo
from odoo.http import Session
from odoo.tools import config, reset_cached_properties

from odoo.addons.base.tests.common import HttpCaseWithUserDemo
from odoo.addons.test_http.utils import MemoryGeoipResolver, MemorySessionStore

HTTP_DATETIME_FORMAT = "%a, %d %b %Y %H:%M:%S GMT"


class TestHttpBase(HttpCaseWithUserDemo):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        geoip_resolver = MemoryGeoipResolver()
        session_store = MemorySessionStore(session_class=Session)

        reset_cached_properties(odoo.http.root)
        cls.addClassCleanup(reset_cached_properties, odoo.http.root)
        cls.classPatch(
            config,
            "options",
            config.options.new_child(
                {"server_wide_modules": ["base", "web", "rpc", "test_http"]}
            ),
        )
        cls.classPatch(odoo.http.Application, "session_store", session_store)
        cls.classPatch(odoo.http.Application, "geoip_city_db", geoip_resolver)
        cls.classPatch(odoo.http.Application, "geoip_country_db", geoip_resolver)

    def setUp(self):
        super().setUp()
        odoo.http.root.session_store.store.clear()
        # Per-test isolation for the monodb-detection memo (see the url_open
        # helpers below); also dropped after the test so it can never leak a
        # patched value into unrelated tests.
        odoo.http.request_class.clear_monodb_cache()
        self.addCleanup(odoo.http.request_class.clear_monodb_cache)

    def db_url_open(self, url, *args, allow_redirects=False, **kwargs):
        # The monodb-detection list is memoised per (host, TTL bucket); drop it
        # so this real-db_list request is not served a value cached by a prior
        # patched (nodb/multidb) request in the same bucket.
        odoo.http.request_class.clear_monodb_cache()
        return self.url_open(url, *args, allow_redirects=allow_redirects, **kwargs)

    def nodb_url_open(self, url, *args, allow_redirects=False, **kwargs):
        # Patch at multiple levels for code accessing via different import paths.
        # The monodb fast path now reads the host-independent ``_list_all_dbs``
        # seam (see ``request_class._all_dbs_cached``) instead of ``db_list``.
        with (
            patch("odoo.http.db_list") as db_list1,
            patch("odoo.http.db_filter") as db_filter1,
            patch("odoo.http.request_class._list_all_dbs") as list_all_dbs2,
            patch("odoo.http.request_class.db_filter") as db_filter2,
        ):
            db_list1.return_value = []
            list_all_dbs2.return_value = []
            for db_filter in (db_filter1, db_filter2):
                db_filter.return_value = []
            # Clear AFTER patching so the request sees the patched seam, not a
            # value cached under a previous patch in the same TTL bucket.
            odoo.http.request_class.clear_monodb_cache()
            return self.url_open(url, *args, allow_redirects=allow_redirects, **kwargs)

    def multidb_url_open(self, url, *args, allow_redirects=False, dblist=(), **kwargs):
        dblist = dblist or self.db_list
        assert len(dblist) >= 2, "There should be at least 2 databases"
        # Patch at multiple levels:
        # - odoo.http.* for code accessing via module (e.g., web.controllers.utils uses http.db_filter)
        # - odoo.http.request_class.* for db_filter/_list_all_dbs (imported there from helpers)
        # - odoo.http._serve.Registry: THE effective dispatch patch — the only
        #   Registry(self.db) call site, in _serve_db → _acquire_registry_cursor.
        # - odoo.http.request_class.Registry: a forward-defensive no-op — that name
        #   has no call site today (annotation-only), patched so a future override
        #   that calls Registry from request_class's namespace stays covered.
        with (
            patch("odoo.http.db_list") as db_list1,
            patch("odoo.http.db_filter") as db_filter1,
            patch("odoo.http.request_class._list_all_dbs") as list_all_dbs2,
            patch("odoo.http.request_class.db_filter") as db_filter2,
            patch("odoo.http.request_class.Registry") as Registry,
            patch("odoo.http._serve.Registry") as ServeRegistry,
        ):
            # The monodb fast path reads the unfiltered ``_list_all_dbs`` seam;
            # feed it the full ``dblist`` so ``db_filter`` keeps >= 2 entries and
            # the request is NOT mis-detected as monodb (the real db name being in
            # ``dblist`` would otherwise filter the real catalog down to one).
            db_list1.return_value = dblist
            list_all_dbs2.return_value = dblist
            for db_filter in (db_filter1, db_filter2):
                db_filter.side_effect = lambda dbs, host=None: [
                    db for db in dbs if db in dblist
                ]
            Registry.return_value = self.registry
            ServeRegistry.return_value = self.registry
            # Clear AFTER patching so the request sees the patched db_list, not a
            # value cached under a previous patch in the same TTL bucket.
            odoo.http.request_class.clear_monodb_cache()
            return self.url_open(url, *args, allow_redirects=allow_redirects, **kwargs)

    def parse_http_cache_control(self, cache_control):
        return parse_cache_control_header(cache_control, None, ResponseCacheControl)

    def assertCacheControl(self, response, cache_control):
        self.assertEqual(
            self.parse_http_cache_control(response.headers["Cache-Control"]),
            self.parse_http_cache_control(cache_control),
        )

    def parse_http_expires(self, expires):
        return datetime.strptime(expires, HTTP_DATETIME_FORMAT).replace(tzinfo=UTC)
