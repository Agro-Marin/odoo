import logging
import operator
import re
import secrets
from io import BytesIO
from unittest.mock import patch

import requests

import odoo
from odoo.modules.registry import Registry
from odoo.tests.common import BaseCase, HttpCase, tagged
from odoo.tools import config


@tagged("web_http", "web_db")
class TestDatabaseManager(HttpCase):
    def test_database_manager(self):
        if not config["list_db"]:
            self.skipTest("list_db is disabled")
        res = self.url_open("/web/database/manager")
        self.assertEqual(res.status_code, 200)

        # Actions scoped to an existing database
        self.assertIn(".o_database_backup", res.text)
        self.assertIn(".o_database_duplicate", res.text)
        self.assertIn(".o_database_delete", res.text)

        # Actions not tied to an existing database
        self.assertIn(".o_database_create", res.text)
        self.assertIn(".o_database_restore", res.text)


@tagged("-at_install", "post_install", "-standard", "database_operations")
class TestDatabaseOperations(BaseCase):
    def setUp(self):
        self.password = secrets.token_hex()

        # monkey-patch password verification. ``verify_admin_password`` is a
        # method on the ``configmanager`` class (the ``config`` singleton's
        # type) — patching the bare module path ``odoo.tools.config`` fails
        # because the module never had a top-level ``verify_admin_password``
        # function; the same name on ``odoo.tools.config`` resolves to the
        # singleton only via the ``from .config import config`` rebinding in
        # ``odoo/tools/__init__.py``, which ``mock.patch``'s importlib lookup
        # does not honor.
        self.verify_admin_password_patcher = patch(
            "odoo.tools.config.configmanager.verify_admin_password",
            self.password.__eq__,
        )
        self.startPatcher(self.verify_admin_password_patcher)

        self.assertEqual(len(config["db_name"]), 1)
        self.db_name = config["db_name"][0]

        # Restrict dbfilter to this db's family so list_dbs_filtered() only
        # ever sees databases this test itself creates/drops.
        self.addCleanup(operator.setitem, config, "dbfilter", config["dbfilter"])
        config["dbfilter"] = self.db_name + ".*"

        self.base_databases = self.list_dbs_filtered()
        self.session = requests.Session()
        self.session.get(self.url("/web/database/manager"))

    def tearDown(self):
        self.assertEqual(
            self.list_dbs_filtered(),
            self.base_databases,
            "No database should have been created or removed at the end of this test",
        )

    def list_dbs_filtered(self):
        return {
            db
            for db in odoo.service.db.list_dbs(True)
            if re.match(config["dbfilter"], db)
        }

    def url(self, path):
        return HttpCase.base_url() + path

    def assertDbs(self, dbs):
        self.assertEqual(self.list_dbs_filtered() - self.base_databases, set(dbs))

    def url_open_drop(self, dbname):
        res = self.session.post(
            self.url("/web/database/drop"),
            data={
                "master_pwd": self.password,
                "name": dbname,
            },
            allow_redirects=False,
        )
        res.raise_for_status()
        return res

    def test_database_creation(self):
        self.assertTrue(odoo.tools.config.verify_admin_password(self.password))

        test_db_name = self.db_name + "-test-database-creation"
        self.assertNotIn(test_db_name, self.list_dbs_filtered())
        res = self.session.post(
            self.url("/web/database/create"),
            data={
                "master_pwd": self.password,
                "name": test_db_name,
                "login": "admin",
                "password": "admin",
                "lang": "en_US",
                "phone": "",
            },
            allow_redirects=False,
        )
        self.assertEqual(res.status_code, 303)
        self.assertIn("/odoo", res.headers["Location"])
        self.assertDbs([test_db_name])

        res = self.url_open_drop(test_db_name)
        self.assertEqual(res.status_code, 303)
        self.assertIn("/web/database/manager", res.headers["Location"])
        self.assertDbs([])

    def test_database_duplicate(self):
        test_db_name = self.db_name + "-test-database-duplicate"
        self.assertNotIn(test_db_name, self.list_dbs_filtered())
        res = self.session.post(
            self.url("/web/database/duplicate"),
            data={
                "master_pwd": self.password,
                "name": self.db_name,
                "new_name": test_db_name,
            },
            allow_redirects=False,
        )
        self.assertEqual(res.status_code, 303)
        self.assertIn("/web/database/manager", res.headers["Location"])
        self.assertDbs([test_db_name])

        res = self.url_open_drop(test_db_name)
        self.assertIn("/web/database/manager", res.headers["Location"])
        self.assertDbs([])

    def test_database_restore(self):
        test_db_name = self.db_name + "-test-database-restore"
        self.assertNotIn(test_db_name, self.list_dbs_filtered())

        res = self.session.post(
            self.url("/web/database/backup"),
            data={
                "master_pwd": self.password,
                "name": self.db_name,
            },
            allow_redirects=False,
            stream=True,
        )
        res.raise_for_status()
        datetime_pattern = r"\d\d\d\d-\d\d-\d\d_\d\d-\d\d-\d\d"
        self.assertRegex(
            res.headers.get("Content-Disposition"),
            rf"attachment; filename\*=UTF-8''{self.db_name}_{datetime_pattern}\.zip",
        )
        backup_file = BytesIO()
        backup_file.write(res.content)
        self.assertGreater(backup_file.tell(), 0, "The backup seems corrupted")

        # Restore the backup under a different name (i.e. a duplicate)
        # Patch the CONSUMING namespace (``odoo.http.wrappers`` binds the
        # constant at import time to set ``HTTPRequest.max_content_length``);
        # patching the ``odoo.http`` re-export never reaches it, so the
        # 1024-byte subtest below silently ran with the real 128MiB limit and
        # could not detect a broken per-route ``max_content_length=None``
        # override on /web/database routes.
        with (
            self.subTest(DEFAULT_MAX_CONTENT_LENGTH=None),
            patch.object(odoo.http.wrappers, "DEFAULT_MAX_CONTENT_LENGTH", None),
        ):
            backup_file.seek(0)
            self.session.post(
                self.url("/web/database/restore"),
                data={
                    "master_pwd": self.password,
                    "name": test_db_name,
                    "copy": True,
                },
                files={
                    "backup_file": backup_file,
                },
                allow_redirects=False,
            ).raise_for_status()
            self.assertDbs([test_db_name])
            self.url_open_drop(test_db_name)

        # /web/database routes set max_content_length=None, so the global
        # DEFAULT_MAX_CONTENT_LENGTH must not reject this upload.
        with (
            self.subTest(DEFAULT_MAX_CONTENT_LENGTH=1024),
            patch.object(odoo.http.wrappers, "DEFAULT_MAX_CONTENT_LENGTH", 1024),
        ):
            backup_file.seek(0)
            self.session.post(
                self.url("/web/database/restore"),
                data={
                    "master_pwd": self.password,
                    "name": test_db_name,
                    "copy": True,
                },
                files={
                    "backup_file": backup_file,
                },
                allow_redirects=False,
            ).raise_for_status()
        self.assertDbs([test_db_name])
        self.url_open_drop(test_db_name)

    def test_drop_nonexistent_database(self):
        """Dropping a database that doesn't exist must show an error page, not
        silently redirect as if the operation succeeded."""
        nonexistent = self.db_name + "-does-not-exist-xyz"
        res = self.session.post(
            self.url("/web/database/drop"),
            data={"master_pwd": self.password, "name": nonexistent},
            allow_redirects=False,
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("error", res.text.lower())
        self.assertDbs([])

    def test_backup_invalid_format_rejected(self):
        """An unrecognised backup_format must return an error page, not crash or
        pass unsanitised input to pg_dump."""
        res = self.session.post(
            self.url("/web/database/backup"),
            data={
                "master_pwd": self.password,
                "name": self.db_name,
                "backup_format": "exe",  # not in {"zip", "dump"}
            },
            allow_redirects=False,
        )
        self.assertEqual(res.status_code, 200)  # Error page, not streaming response
        self.assertIn("error", res.text.lower())

    def test_database_http_registries(self):
        """Dropping a database's connection in one worker must not break
        other workers that still hold a (now stale) registry for it."""

        #
        # Setup
        #

        test_db_name = self.db_name + "-test-database-duplicate"
        res = self.session.post(
            self.url("/web/database/duplicate"),
            data={
                "master_pwd": self.password,
                "name": self.db_name,
                "new_name": test_db_name,
            },
            allow_redirects=False,
        )

        registry = Registry(test_db_name)
        cr = registry.cursor()
        self.assertIn(test_db_name, Registry.registries)

        # Drop the database, but stub out close_db so our cursor/registry
        # objects survive to simulate a worker that still holds them.
        with patch("odoo.db.close_db") as close_db:
            res = self.url_open_drop(test_db_name)
        close_db.assert_called_once_with(test_db_name)

        # Simulate a client session that was connected to the now-dropped db.
        session_store = odoo.http.root.session_store
        session = session_store.new()
        session.update(odoo.http.get_default_session(), db=test_db_name)
        session.context["lang"] = odoo.http.DEFAULT_LANG
        self.session.cookies["session_id"] = session.sid

        # Reinject the stale registry into the LRU cache to simulate the
        # other worker still holding it after the drop.
        patcher = patch.dict(Registry.registries, {test_db_name: registry})
        registries = patcher.start()
        self.addCleanup(patcher.stop)

        #
        # Tests
        #

        # The other worker doesn't have a registry in its LRU cache for
        # that session database.
        with self.subTest(msg="Registry.init() fails"):
            session_store.save(session)
            registries.pop(test_db_name, None)
            with self.assertLogs("odoo.db", logging.INFO) as capture:
                res = self.session.get(self.url("/web/health"))
            self.assertEqual(res.status_code, 200)
            self.assertEqual(session_store.get(session.sid)["db"], None)
            self.assertEqual(
                capture.output,
                [
                    "INFO:odoo.db:Connection to the database failed",
                ],
            )

        # The other worker has a registry in its LRU cache for that
        # session database. But it doesn't have a connection to the sql
        # database.
        with self.subTest(msg="Registry.cursor() fails"):
            session_store.save(session)
            registries[test_db_name] = registry
            with (
                self.assertLogs("odoo.db", logging.INFO) as capture,
                patch.object(Registry, "__new__", return_value=registry),
            ):
                res = self.session.get(self.url("/web/health"))
            self.assertEqual(res.status_code, 200)
            self.assertEqual(session_store.get(session.sid)["db"], None)
            self.assertEqual(
                capture.output,
                [
                    "INFO:odoo.db:Connection to the database failed",
                ],
            )

        # The other worker has a registry in its LRU cache for that
        # session database. It also has a (now broken) connection to the
        # sql database.
        with self.subTest(msg="Registry.check_signaling() fails"):
            session_store.save(session)
            registries[test_db_name] = registry
            with (
                self.assertLogs("odoo.db", logging.ERROR) as capture,
                patch.object(Registry, "__new__", return_value=registry),
                patch.object(Registry, "cursor", return_value=cr),
            ):
                res = self.session.get(self.url("/web/health"))
            self.assertEqual(res.status_code, 200)
            self.assertEqual(session_store.get(session.sid)["db"], None)
            self.maxDiff = None
            self.assertRegex(
                capture.output[0],
                (
                    r"^ERROR:odoo\.db\.cursor:bad query:(?s:.*?)"
                    r"ERROR: terminating connection due to administrator command\s+"
                    r"server closed the connection unexpectedly\s+"
                    r"This probably means the server terminated abnormally\s+"
                    r"before or while processing the request\.$"
                ),
            )
