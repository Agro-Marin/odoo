import inspect
import io
from http import HTTPStatus
from unittest.mock import patch

from lxml import etree

from odoo import http
from odoo.libs.json import dumps as json_dumps
from odoo.tests.common import BaseCase, HttpCase, TransactionCase, tagged
from odoo.tools import mute_logger

from odoo.addons.web.controllers.binary import Binary


@tagged("web_http", "web_controllers_audit")
class TestBarcodeInvalidType(HttpCase):
    def test_barcode_invalid_type_returns_400(self):
        response = self.url_open("/report/barcode/TOTALLY_INVALID_TYPE/testvalue")
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)


@tagged("web_controllers_audit")
class TestBarcodeDimensionClamp(BaseCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from odoo.addons.web.controllers.report import (
            _MAX_BARCODE_DIM,
            _clamp_barcode_dimension,
        )

        cls._clamp = staticmethod(_clamp_barcode_dimension)
        cls._max = _MAX_BARCODE_DIM

    def test_oversized_is_clamped_to_max(self):
        self.assertEqual(self._clamp(100_000, 600), self._max)
        self.assertEqual(self._clamp(self._max + 1, 100), self._max)

    def test_reasonable_value_passes_through(self):
        self.assertEqual(self._clamp(200, 600), 200)
        self.assertEqual(self._clamp("300", 600), 300)

    def test_invalid_or_nonpositive_falls_back_to_default(self):
        self.assertEqual(self._clamp("not-a-number", 600), 600)
        self.assertEqual(self._clamp(None, 100), 100)
        self.assertEqual(self._clamp(0, 600), 600)
        self.assertEqual(self._clamp(-5, 100), 100)


@tagged("web_http", "web_controllers_audit")
class TestBarcodeDimensionClampHttp(HttpCase):
    def test_huge_dimensions_do_not_500(self):
        response = self.url_open(
            "/report/barcode/Code128/hello?width=100000&height=100000"
        )
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    def test_clamped_single_dimension_renders(self):
        response = self.url_open(
            "/report/barcode/Code128/hello?width=100000&height=100"
        )
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.headers.get("Content-Type"), "image/png")

    def test_oversized_value_rejected(self):
        huge = "A" * 40000
        response = self.url_open(f"/report/barcode/Code128/{huge}")
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    def test_normal_value_still_renders(self):
        response = self.url_open("/report/barcode/Code128/HELLO-12345")
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.headers.get("Content-Type"), "image/png")


@tagged("web_http", "web_controllers_audit")
class TestImageDimensionGuard(HttpCase):
    def test_garbage_width_does_not_500(self):
        response = self.url_open("/web/image/99999999?width=abc&height=xyz")
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.headers.get("Content-Type"), "image/png")


@tagged("web_controllers_audit")
class TestCsvFormulaNeutralization(BaseCase):
    def test_dangerous_leading_chars_are_prefixed(self):
        from odoo.addons.web.controllers.export import CSVExport

        rows = [["=cmd"], ["+cmd"], ["-cmd"], ["@cmd"], ["\t=x"]]
        out = CSVExport().from_data([], ["header"], rows).decode()
        for payload in ("=cmd", "+cmd", "-cmd", "@cmd"):
            self.assertIn(
                f"'{payload}",
                out,
                f"{payload!r} must be apostrophe-prefixed to defuse the formula",
            )

    def test_benign_values_are_not_mangled(self):
        from odoo.addons.web.controllers.export import CSVExport

        out = CSVExport().from_data([], ["header"], [["a=b"], ["safe"]]).decode()
        self.assertIn("a=b", out)
        self.assertNotIn("'a=b", out)
        self.assertNotIn("'safe", out)


@tagged("web_http", "web_controllers_audit")
class TestPivotNegativeInputs(HttpCase):
    def test_export_xlsx_negative_measure_count(self):
        self.authenticate("admin", "admin")
        jdata = {
            "title": "Test",
            "model": "res.partner",
            "measure_count": -5,
            "origin_count": 1,
            "col_group_headers": [],
            "measure_headers": [],
            "origin_headers": [],
            "rows": [],
        }
        response = self.url_open(
            "/web/pivot/export_xlsx",
            data={
                "data": json_dumps(jdata),
                "csrf_token": http.Request.csrf_token(self),
            },
        )
        self.assertEqual(response.status_code, HTTPStatus.OK)

    def test_export_xlsx_negative_header_width(self):
        self.authenticate("admin", "admin")
        jdata = {
            "title": "Test",
            "model": "res.partner",
            "measure_count": 1,
            "origin_count": 1,
            "col_group_headers": [[{"title": "A", "width": -3, "height": 1}]],
            "measure_headers": [],
            "origin_headers": [],
            "rows": [],
        }
        response = self.url_open(
            "/web/pivot/export_xlsx",
            data={
                "data": json_dumps(jdata),
                "csrf_token": http.Request.csrf_token(self),
            },
        )
        self.assertEqual(response.status_code, HTTPStatus.OK)

    def test_export_xlsx_huge_indent_is_clamped(self):
        self.authenticate("admin", "admin")
        jdata = {
            "title": "Test",
            "model": "res.partner",
            "measure_count": 1,
            "origin_count": 1,
            "col_group_headers": [],
            "measure_headers": [],
            "origin_headers": [],
            "rows": [{"indent": 400_000_000, "title": "row", "values": []}],
        }
        response = self.url_open(
            "/web/pivot/export_xlsx",
            data={
                "data": json_dumps(jdata),
                "csrf_token": http.Request.csrf_token(self),
            },
        )
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertLess(len(response.content), 1_000_000)


@tagged("web_http", "web_controllers_audit")
class TestWebClientOpenRedirect(HttpCase):
    def test_backslash_redirect_rejected(self):
        self.authenticate("admin", "admin")
        response = self.url_open(
            "/odoo?redirect=%2F%5Cevil.com",
            allow_redirects=False,
        )
        location = response.headers.get("Location", "")
        self.assertNotIn("evil.com", location)

    def test_local_path_redirect_accepted(self):
        self.authenticate("admin", "admin")
        response = self.url_open(
            "/odoo?redirect=/odoo/contacts",
            allow_redirects=False,
        )
        self.assertEqual(response.status_code, HTTPStatus.SEE_OTHER)
        self.assertIn("/odoo/contacts", response.headers.get("Location", ""))


@tagged("web_controllers_audit")
class TestCompanyLogoFallback(TransactionCase):
    def test_fallback_uses_hardcoded_logo_png(self):
        source = inspect.getsource(Binary.company_logo)
        self.assertIn('file_path("web/static/img/logo.png")', source)
        self.assertNotIn(
            'file_path(f"web/static/img/{imgname}{imgext}")',
            source,
            "Fallback must not use imgext — it may have been mutated to '.svg'",
        )


@tagged("web_http", "web_controllers_audit")
class TestDatabaseRestoreLogging(HttpCase):
    def test_restore_logs_exception_on_failure(self):
        with (
            patch(
                "odoo.tools.config.configmanager.verify_admin_password",
                return_value=False,
            ),
            patch("odoo.service.db.check_super"),
            patch(
                "odoo.service.db.restore_db",
                side_effect=Exception("simulated restore error"),
            ),
            self.assertLogs(
                "odoo.addons.web.controllers.database", level="ERROR"
            ) as log_cm,
        ):
            response = self.url_open(
                "/web/database/restore",
                data={
                    "master_pwd": "admin",
                    "name": "test_audit_nonexistent_db",
                    "copy": "false",
                    "neutralize_database": "false",
                },
                files={
                    "backup_file": (
                        "test.zip",
                        io.BytesIO(b"fake content"),
                        "application/zip",
                    )
                },
            )
        self.assertIn("Database restore error", response.text)
        self.assertTrue(
            any("Database restore error" in msg for msg in log_cm.output),
            f"Expected 'Database restore error' in logs, got: {log_cm.output}",
        )


@tagged("web_http", "web_controllers_audit")
class TestExportGroupbyValidation(HttpCase):
    @mute_logger("odoo.addons.web.controllers.export")
    def test_invalid_groupby_field_returns_descriptive_error(self):
        self.authenticate("admin", "admin")
        data = json_dumps(
            {
                "model": "res.partner",
                "fields": [{"name": "name", "label": "Name"}],
                "ids": [],
                "domain": [],
                "import_compat": False,
                "groupby": ["totally_nonexistent_xyz"],
            }
        )
        response = self.url_open(
            "/web/export/xlsx",
            data={"data": data, "csrf_token": http.Request.csrf_token(self)},
        )
        self.assertEqual(response.status_code, HTTPStatus.INTERNAL_SERVER_ERROR)
        self.assertIn("Unknown groupby fields", response.text)
        self.assertIn("totally_nonexistent_xyz", response.text)


@tagged("web_controllers_audit")
class TestIsLocalUrl(BaseCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from odoo.addons.web.controllers.utils import _is_local_url

        cls._is_local_url = staticmethod(_is_local_url)

    def test_local_paths_accepted(self):
        self.assertTrue(self._is_local_url("/odoo"))
        self.assertTrue(self._is_local_url("/odoo/contacts"))
        self.assertTrue(self._is_local_url("/web"))
        self.assertTrue(self._is_local_url("/web/login"))

    def test_protocol_relative_rejected(self):
        self.assertFalse(self._is_local_url("//evil.com"))

    def test_backslash_trick_rejected(self):
        self.assertFalse(self._is_local_url("/\\evil.com"))

    def test_absolute_url_rejected(self):
        self.assertFalse(self._is_local_url("https://evil.com"))
        self.assertFalse(self._is_local_url("http://evil.com/odoo"))

    def test_embedded_tab_newline_rejected(self):
        for vector in (
            "/\t\t//evil.com",
            "/\r\r//evil.com",
            "/\n\n//evil.com",
            "/\t/\t/evil.com",
            "\t//evil.com",
        ):
            with self.subTest(vector=vector):
                self.assertFalse(self._is_local_url(vector))

    def test_multiple_leading_slashes_rejected(self):
        self.assertFalse(self._is_local_url("///evil.com"))
        self.assertFalse(self._is_local_url("////evil.com"))

    def test_whitespace_only_rejected(self):
        self.assertFalse(self._is_local_url("\t"))
        self.assertFalse(self._is_local_url("\r\n"))

    def test_empty_and_none_rejected(self):
        self.assertFalse(self._is_local_url(""))
        self.assertFalse(self._is_local_url(None))


@tagged("web_controllers_audit")
class TestJsonHelpers(TransactionCase):
    def test_get_groupby_with_default_group_by(self):
        from odoo.addons.web.controllers.json_helpers import get_groupby

        tree = etree.fromstring(
            '<kanban default_group_by="partner_id"><templates/></kanban>'
        )
        groupby, fields = get_groupby(tree)
        self.assertIsNone(groupby)
        self.assertEqual(fields, ["partner_id"])

    def test_get_groupby_no_default_group_by(self):
        from odoo.addons.web.controllers.json_helpers import get_groupby

        tree = etree.fromstring("<kanban><templates/></kanban>")
        groupby, fields = get_groupby(tree)
        self.assertIsNone(groupby)
        self.assertIsNone(fields)

    def test_get_groupby_explicit_param_overrides_view(self):
        from odoo.addons.web.controllers.json_helpers import get_groupby

        tree = etree.fromstring(
            '<kanban default_group_by="stage_id"><templates/></kanban>'
        )
        groupby, fields = get_groupby(tree, groupby="partner_id,user_id")
        self.assertEqual(groupby, ["partner_id", "user_id"])
        self.assertIsNone(fields)

    def test_get_view_id_and_type_returns_false_for_unset_view(self):
        from odoo.addons.web.controllers.json_helpers import get_view_id_and_type

        action = self.env["ir.actions.act_window"].create(
            {
                "name": "_AuditTest",
                "res_model": "res.partner",
                "view_mode": "list,form",
            }
        )
        view_id, view_type = get_view_id_and_type(action, "list")
        self.assertIs(
            view_id, False, "Must be False (Odoo 'no ID' convention), not None"
        )
        self.assertEqual(view_type, "list")
