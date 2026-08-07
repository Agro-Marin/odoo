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


@tagged("web_http", "web_db")
class TestDatabaseManager(HttpCase):
    def test_database_manager(self):
        if not config["list_db"]:
            self.skipTest("list_db is disabled")
        res = self.url_open("/web/database/manager")
        self.assertEqual(res.status_code, 200)

        # a doctype written in the template does not survive the lxml round
        # trip; without one the page renders in quirks mode, where <body>
        # stretches to the viewport and Bootstrap is unsupported
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
    """The page's JS addresses fields by id and its labels by ``for``, while the
    same partials (``master_input``, ``create_form``) are included once per
    form: both have to stay unambiguous in every combination of values."""

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
            # no database at all renders the create form twice: inline, and in
            # the create modal
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

    def test_backup_declares_its_length(self):
        """A backup must announce Content-Length and really be an archive.

        Without a declared length the body is delimited by nothing but the
        connection closing, so a transfer cut short mid-download — a flaky link,
        a proxy giving up on a multi-GB response — reaches the browser as a
        *successful* download of a truncated archive.  Nothing surfaces until
        someone tries to restore it.

        The archive check guards the sibling failure: the controller reports
        dump errors by rendering an HTML page with status 200, which the browser
        saves under the .zip name as though it were the backup.
        """
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
        """An unrecognised backup_format must return an error page, not crash or
        pass unsanitised input to pg_dump."""
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
        """Dropping a database's connection in one worker must not break
        other workers that still hold a (now stale) registry for it."""


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
        close_db.assert_called_once_with(test_db_name)

        session_store = odoo.http.root.session_store
        session = session_store.new()
        session.update(odoo.http.get_default_session(), db=test_db_name)
        session.context["lang"] = odoo.http.DEFAULT_LANG
        self.session.cookies["session_id"] = session.sid

        patcher = patch.dict(Registry.registries, {test_db_name: registry})
        registries = patcher.start()
        self.addCleanup(patcher.stop)


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
