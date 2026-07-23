import logging
from contextlib import closing
from unittest.mock import patch
from urllib.parse import urlsplit

import psycopg
import requests

import odoo
from odoo.db import PoolError, close_db, db_connect
from odoo.libs.web.urls import urljoin
from odoo.modules.registry import Registry
from odoo.tests import HOST, BaseCase, Like, get_db_name, tagged
from odoo.tools import SQL, config, mute_logger, reset_cached_properties

"""
RCO:
The other "what could go wrong" I can think about:

* you cannot connect to PostgreSQL
* the database does not exists
* the database is corrupted:
* + table ir_module_module does not exist or misses some columns
* + the "sequences" don't exist
* the database version doesn't match the server version (version is inferred from module base, I think)
* you cannot import some modules (in the Python sense)
* some modules are marked to be installed/upgraded/uninstalled and that fails (that's part of Registry.new)
"""
# TODO: write some tests for those too


def duplicate_db(db_source, db_dest):
    query = SQL(
        "CREATE DATABASE %s ENCODING 'unicode' TEMPLATE %s",
        SQL.identifier(db_dest),
        SQL.identifier(db_source),
    )
    with closing(db_connect("postgres").cursor()) as cr:
        cr.connection.autocommit = True
        cr.execute(query)


def drop_db(db):
    query = SQL("DROP DATABASE IF EXISTS %s", SQL.identifier(db))
    with closing(db_connect("postgres").cursor()) as cr:
        cr.connection.autocommit = True
        cr.execute(query)


@tagged("-standard", "-at_install", "post_install", "database_breaking")
class TestHttpRegistry(BaseCase):
    @classmethod
    def setUpClass(cls):
        reset_cached_properties(odoo.http.root)
        cls.addClassCleanup(reset_cached_properties, odoo.http.root)
        # ``odoo.conf`` no longer exists in this fork; patch the config chainmap
        # the way ``test_common.TestHttpBase`` does.
        cls.classPatch(
            config,
            "options",
            config.options.new_child(
                {"server_wide_modules": ["base", "web", "rpc", "test_http"]}
            ),
        )
        # ``/test_http/ensure_db`` is a test route; the production constant no
        # longer lists it. Patch the CONSUMING namespace (application.py binds
        # the name at import), so ``_recover_from_registry_error`` strips
        # ``?db=`` for it like it does for ``/web``.
        cls.classPatch(
            odoo.http.application,
            "ENSURE_DB_PATHS",
            odoo.http.application.ENSURE_DB_PATHS | {"/test_http/ensure_db"},
        )

        # make sure there are always many databases, to break monodb.
        # Patch the CONSUMING namespaces, not just the ``odoo.http`` re-exports:
        # ``request_class`` binds ``db_filter`` / ``_list_all_dbs`` at import
        # time (see ``test_common.multidb_url_open`` for the same seams), so a
        # patch on ``odoo.http.db_filter`` alone never reaches
        # ``_get_session_and_dbname`` — the real ``db_filter`` then rejects the
        # duplicated databases (``--database`` allowlist) and every test below
        # silently runs against the healthy main database instead.
        cls._db_list = cls.startClassPatcher(patch("odoo.http.db_list"))
        cls._db_list.return_value = ["postgres", get_db_name()]

        def fake_db_filter(dbs, host=None):
            return [db for db in dbs if db in cls._db_list()]

        cls.startClassPatcher(patch("odoo.http.db_filter", side_effect=fake_db_filter))
        cls.startClassPatcher(
            patch("odoo.http.request_class.db_filter", side_effect=fake_db_filter)
        )
        cls.startClassPatcher(
            patch(
                "odoo.http.request_class._list_all_dbs",
                side_effect=lambda force=False: list(cls._db_list()),
            )
        )

    def setUp(self):
        super().setUp()
        self.opener = requests.Session()
        Registry.delete(get_db_name())
        close_db(get_db_name())
        # The monodb-detection memo (5s TTL) must not serve a catalog cached
        # before this test dropped/duplicated databases.
        odoo.http.request_class.clear_monodb_cache()
        self.addCleanup(odoo.http.request_class.clear_monodb_cache)

    def duplicate_current_db(self, db_suffix):
        db_duplicate = f"{get_db_name()}-test-http-registry-{db_suffix}"

        # duplicate the current database
        duplicate_db(db_source=get_db_name(), db_dest=db_duplicate)
        self.addCleanup(drop_db, db_duplicate)
        self.addCleanup(close_db, db_duplicate)
        self._db_list.return_value.append(db_duplicate)
        self.addCleanup(self._db_list.return_value.remove, db_duplicate)

        return db_duplicate

    def authenticate(self, *, db=None):
        session = odoo.http.root.session_store.new()
        session.update(odoo.http.get_default_session(), db=db or get_db_name())
        session.context["lang"] = odoo.http.DEFAULT_LANG
        odoo.http.root.session_store.save(session)
        self.opener.cookies.set("session_id", session.sid, domain=HOST)
        return session

    def url_open(self, path, *, allow_redirects=False):
        if not path.startswith("/"):
            raise ValueError("can only request a relative url")
        url = urljoin(f"http://{HOST}:{odoo.tools.config['http_port']}", path)
        return self.opener.get(url, allow_redirects=allow_redirects)

    def test_signaling(self):
        # open a registry + session on the current db
        self.authenticate()
        res = self.url_open("/test_http/ensure_db")
        self.assertEqual(res.status_code, 200)

        # invalidate the registry of the current db
        with Registry(get_db_name()).cursor() as cr:
            cr.execute("INSERT INTO orm_signaling_registry default values")

        # the registry should rebuild itself just fine
        with self.assertLogs("odoo.registry", logging.INFO) as capture:
            res = self.url_open("/test_http/ensure_db")
            self.assertEqual(res.status_code, 200)
        self.assertEqual(
            capture.output,
            [
                "INFO:odoo.registry:Reloading the model registry after database signaling.",
                Like("INFO:odoo.registry:Registry loaded in ...s"),
            ],
        )

    def test_missing_db(self):
        db_duplicate = self.duplicate_current_db("drop")

        # open a registry + session on the duplicated db
        session = self.authenticate(db=db_duplicate)
        res = self.url_open("/test_http/ensure_db")
        self.assertEqual(res.status_code, 200)

        # drop the duplicate, leave the session and registry dangling
        close_db(db_duplicate)
        drop_db(db_duplicate)
        self.assertIn(db_duplicate, Registry.registries)  # dangling

        # the registry is unusable, make sure the system recovers fine
        with self.assertLogs("odoo.http.application", logging.WARNING) as capture:
            res = self.url_open("/test_http/ensure_db")
            res.raise_for_status()
            # The db is CONFIRMED dropped (RegistryError.db_absent=True): unlike
            # a catalog-unreachable blip, the logout must be durable — a session
            # bound to a dead database must not stay logged in on disk.
            self.assertFalse(
                odoo.http.root.session_store.get(session.sid).db,
                "A session on a dropped database must be durably logged out.",
            )
            self.authenticate(db=db_duplicate)  # session was dropped
            res_query = self.url_open(f"/test_http/ensure_db?db={db_duplicate}")
            res_query.raise_for_status()

        self.assertEqual(
            [
                (
                    res.status_code,
                    urlsplit(res.headers.get("Location", "")).path,
                ),
                (
                    res_query.status_code,
                    urlsplit(res_query.headers.get("Location", "")).path,
                ),
            ],
            [(303, "/web/database/selector")] * 2,
            "It should not redirect back on /test_http/ensure_db.",
        )
        self.assertEqual(
            capture.output,
            [
                Like(
                    "WARNING:odoo.http.application:Database or registry unusable, trying without\n"
                    f'Traceback...database "{db_duplicate}" does not exist...'
                )
            ]
            * 2,
        )

    def test_catalog_unreachable_keeps_session(self):
        # A transient outage where even the catalog is unreachable (PostgreSQL
        # restarting) says nothing about the session's database: the request is
        # served db-less ONCE but the session must survive, or a blip forces a
        # site-wide re-login. Only a decidable catalog check (db dropped, or
        # present with a broken registry) may log the session out.
        session = self.authenticate()
        boom = psycopg.OperationalError("server closed the connection unexpectedly")
        with (
            patch("odoo.http._serve.Registry", side_effect=boom),
            patch("odoo.service.db.list_dbs", side_effect=boom),
            self.assertLogs("odoo.http.application", logging.WARNING) as capture,
        ):
            res = self.url_open("/test_http/ensure_db")
        self.assertEqual(
            capture.output,
            [
                Like(
                    "WARNING:odoo.http.application:Database or registry "
                    "unusable, trying without\nTraceback...server closed the "
                    "connection unexpectedly..."
                )
            ],
        )
        self.assertEqual(
            (res.status_code, urlsplit(res.headers.get("Location", "")).path),
            (303, "/web/database/selector"),
            "The request itself degrades to db-less serving.",
        )
        persisted = odoo.http.root.session_store.get(session.sid)
        self.assertEqual(
            persisted.db,
            get_db_name(),
            "A catalog-unreachable blip must not log the session out.",
        )

    def test_pool_error_keeps_session(self):
        # A downed PostgreSQL behind a WARM pool surfaces as PoolError (the
        # pool wraps psycopg_pool's PoolTimeout), NOT as a raw
        # OperationalError — and pool starvation under load raises the same
        # class. Both are transient failures against an existing database:
        # the request must degrade db-less without 500ing (PoolError used to
        # miss the recovery tuple entirely) and WITHOUT durably logging the
        # session out (the catalog still lists the db, but nothing about it
        # is broken).
        session = self.authenticate()
        with (
            patch("odoo.http._serve.Registry") as registry_cls,
            self.assertLogs("odoo.http.application", logging.WARNING),
        ):
            registry_cls.return_value.cursor.side_effect = PoolError(
                "couldn't get a connection after 30.00 sec"
            )
            res = self.url_open("/test_http/ensure_db")
        self.assertEqual(
            (res.status_code, urlsplit(res.headers.get("Location", "")).path),
            (303, "/web/database/selector"),
            "The request itself degrades to db-less serving.",
        )
        persisted = odoo.http.root.session_store.get(session.sid)
        self.assertEqual(
            persisted.db,
            get_db_name(),
            "A transient pool failure must not log the session out.",
        )

    @mute_logger("odoo.db")
    def test_corrupt_ir_module_module_table(self):
        db_duplicate = self.duplicate_current_db("corrupt-irmodule")

        # corrupt the ir_module_module table
        with db_connect(db_duplicate).cursor() as cr:
            cr.execute("""
                ALTER TABLE "ir_module_module" DROP COLUMN "state"
            """)

        # we have a session on that database but no registry
        self.authenticate(db=db_duplicate)

        # impossible to build a registry, make sure the system recovers
        with (
            self.assertLogs("odoo.registry", logging.ERROR) as capture1,
            self.assertLogs("odoo.http.application", logging.WARNING) as capture2,
        ):
            res = self.url_open("/test_http/greeting-public")
            self.assertEqual(res.status_code, 404)
        self.assertEqual(
            capture1.output,
            [
                "ERROR:odoo.registry:Failed to load registry",
            ],
        )
        self.assertEqual(
            capture2.output,
            [
                Like(
                    "WARNING:odoo.http.application:Database or registry unusable, trying without\n"
                    'Traceback...column "state" does not exist...'
                )
            ],
        )

    @mute_logger("odoo.db")
    def test_corrupt_signaling(self):
        db_duplicate = self.duplicate_current_db("corrupt-sequence")

        # open a registry + session on the current db (for first subtest)
        self.authenticate(db=db_duplicate)
        res = self.url_open("/test_http/ensure_db")
        self.assertEqual(res.status_code, 200)

        # drop the signaling sequence
        with db_connect(db_duplicate).cursor() as cr:
            cr.execute("""
                DROP table "orm_signaling_registry"
            """)

        with self.subTest(name="existing registry"):
            # attempt to reuse the registry, make sure the system recovers
            with self.assertLogs("odoo.http.application", logging.WARNING) as capture:
                res = self.url_open("/test_http/greeting-public")
                self.assertEqual(res.status_code, 404)
            self.assertEqual(
                capture.output,
                [
                    Like(
                        "WARNING:odoo.http.application:Database or registry unusable, trying without\n"
                        'Traceback...relation "orm_signaling_registry" does not exist...'
                    )
                ],
            )

        with self.subTest(name="new registry"):
            self.authenticate(db=db_duplicate)
            Registry.delete(db_duplicate)
            # attempt to create a new registry, it should create the
            # missing sequences and go on just fine
            res = self.url_open("/test_http/greeting-public")
            self.assertEqual(res.status_code, 200)
