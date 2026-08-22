import logging
import operator
import re
import secrets
import zipfile
from io import BytesIO
from unittest.mock import patch

import requests
from lxml import html

import odoo
from odoo.modules.registry import Registry
from odoo.service.db import DBNAME_PATTERN
from odoo.tests.common import BaseCase, HttpCase, tagged
from odoo.tools import config

from odoo.addons.web.controllers.database import render_database_manager

PROBE_URL = "/web/database/selector"


@tagged("web_http", "web_db")
class TestDatabaseManager(HttpCase):
    def test_database_manager(self):
        if not config["list_db"]:
            self.skipTest("list_db is disabled")
        res = self.url_open("/web/database/manager")
        self.assertEqual(res.status_code, 200)

        self.assertTrue(
            res.text.startswith("<!DOCTYPE html>"),
            "the database manager must not be served in quirks mode",
        )

        self.assertIn(".o_database_backup", res.text)
        self.assertIn(".o_database_duplicate", res.text)
        self.assertIn(".o_database_delete", res.text)

        self.assertIn(".o_database_create", res.text)
        self.assertIn(".o_database_restore", res.text)


@tagged("web_db")
class TestDatabaseManagerMarkup(BaseCase):
    def _render(self, **overrides):
        values = {
            "manage": True,
            "insecure": False,
            "list_db": True,
            "langs": [("en_US", "English")],
            "countries": [("us", "United States")],
            "pattern": DBNAME_PATTERN,
            "databases": ["db1"],
            "incompatible_databases": [],
            "error": None,
        }
        values.update(overrides)
        return html.document_fromstring(render_database_manager(values))

    def test_ids_are_unique_and_labels_resolve(self):
        for insecure in (False, True):
            for databases in ([], ["db1"]):
                with self.subTest(insecure=insecure, databases=databases):
                    doc = self._render(insecure=insecure, databases=databases)
                    ids = doc.xpath("//*/@id")
                    self.assertCountEqual(ids, set(ids), "duplicate element ids")
                    targets = set(ids)
                    for label_for in doc.xpath("//label/@for"):
                        self.assertIn(label_for, targets, "label points at no element")

    def test_master_password_input_is_hidden_only_in_the_master_form(self):
        doc = self._render(insecure=True)
        hidden = doc.xpath("//input[@name='master_pwd'][@type='hidden']")
        self.assertEqual(len(hidden), 1)
        self.assertEqual(
            hidden[0].xpath("ancestor::form/@action"),
            ["/web/database/change_password"],
        )


@tagged("-at_install", "post_install", "-standard", "database_operations")
class TestDatabaseOperations(BaseCase):
    def setUp(self):
        self.password = secrets.token_hex()

        self.verify_admin_password_patcher = patch(
            "odoo.tools.config.configmanager.verify_admin_password",
            self.password.__eq__,
        )
        self.startPatcher(self.verify_admin_password_patcher)

        self.assertEqual(len(config["db_name"]), 1)
        self.db_name = config["db_name"][0]

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
        nonexistent = self.db_name + "-does-not-exist-xyz"
        res = self.session.post(
            self.url("/web/database/drop"),
            data={"master_pwd": self.password, "name": nonexistent},
            allow_redirects=False,
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("error", res.text.lower())
        self.assertDbs([])

    def test_backup_declares_its_length(self):
        res = self.session.post(
            self.url("/web/database/backup"),
            data={"master_pwd": self.password, "name": self.db_name},
            allow_redirects=False,
            stream=True,
        )
        res.raise_for_status()
        declared = res.headers.get("Content-Length")
        self.assertIsNotNone(
            declared, "the backup response must declare its Content-Length"
        )
        body = res.content
        self.assertEqual(
            int(declared),
            len(body),
            "declared length must match the bytes actually delivered",
        )
        self.assertTrue(
            zipfile.is_zipfile(BytesIO(body)),
            "the backup must be a zip, not an HTML error page served as one",
        )

    def test_backup_invalid_format_rejected(self):
        res = self.session.post(
            self.url("/web/database/backup"),
            data={
                "master_pwd": self.password,
                "name": self.db_name,
                "backup_format": "exe",
            },
            allow_redirects=False,
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("error", res.text.lower())

    def test_database_http_registries(self):
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

        with patch("odoo.db.close_db") as close_db:
            res = self.url_open_drop(test_db_name)
        self.assertTrue(close_db.call_args_list, "the drop closed no connection")
        self.assertEqual(
            {args for args, _ in close_db.call_args_list},
            {(test_db_name,)},
            "the drop closed connections to a database it was not given",
        )

        session_store = odoo.http.root.session_store
        session = session_store.new()
        session.update(odoo.http.get_default_session(), db=test_db_name)
        session.context["lang"] = odoo.http.DEFAULT_LANG
        self.session.cookies["session_id"] = session.sid

        patcher = patch.dict(Registry.registries, {test_db_name: registry})
        registries = patcher.start()
        self.addCleanup(patcher.stop)

        def _assert_degrades_gracefully(capture, *, evicts_stored_session):
            self.assertEqual(res.status_code, 200)
            self.assertTrue(
                [r for r in capture.records if test_db_name in r.getMessage()]
                or [r for r in capture.records if r.levelno >= logging.WARNING],
                f"the unusable database was not reported: {capture.output}",
            )
            stored = session_store.get(session.sid)
            if evicts_stored_session:
                self.assertFalse(
                    stored.get("db"),
                    "a durable registry failure must not leave the stored "
                    "session pointing at the database",
                )
            else:
                self.assertEqual(
                    stored.get("db"),
                    test_db_name,
                    "a transient registry failure must not evict the stored session",
                )

        with self.subTest(msg="Registry.init() fails"):
            session_store.save(session)
            registries.pop(test_db_name, None)
            with self.assertLogs("odoo", logging.INFO) as capture:
                res = self.session.get(self.url(PROBE_URL))
            _assert_degrades_gracefully(capture, evicts_stored_session=True)

        with self.subTest(msg="Registry.cursor() fails"):
            session_store.save(session)
            registries[test_db_name] = registry
            with (
                self.assertLogs("odoo", logging.INFO) as capture,
                patch.object(Registry, "__new__", return_value=registry),
            ):
                res = self.session.get(self.url(PROBE_URL))
            _assert_degrades_gracefully(capture, evicts_stored_session=True)

        with self.subTest(msg="Registry.check_signaling() fails"):
            session_store.save(session)
            registries[test_db_name] = registry
            with (
                self.assertLogs("odoo", logging.INFO) as capture,
                patch.object(Registry, "__new__", return_value=registry),
                patch.object(Registry, "cursor", return_value=cr),
            ):
                res = self.session.get(self.url(PROBE_URL))
            _assert_degrades_gracefully(capture, evicts_stored_session=False)
