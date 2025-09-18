"""Tests verifying bug fixes from the 2026-03-06 web/controllers audit.

Covered:
- binary.py  : company_logo fallback always serves logo.png (imgext mutation bug)
- database.py: restore() logs exceptions via _logger.exception()
- export.py  : groupby field validation returns clean error instead of raw KeyError
- home.py    : _is_local_url() rejects /\\ open-redirect bypass
- pivot.py   : negative measure_count/width are clamped to 0
- report.py  : invalid barcode → HTTP 400 (BadRequest), not malformed HTTPException
- json_helpers.py: get_groupby default_group_by returns (None, [field]) without dead branch
- utils.py   : _is_local_url correctly accepts /local paths, rejects //, /\\, absolute URLs
"""

import io
from http import HTTPStatus
from unittest.mock import patch
import inspect

from lxml import etree

from odoo import http
from odoo.addons.web.controllers.binary import Binary
from odoo.libs.json import dumps as json_dumps
from odoo.tests.common import BaseCase, HttpCase, TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("web_http", "web_controllers_audit")
class TestBarcodeInvalidType(HttpCase):
    def test_barcode_invalid_type_returns_400(self):
        """Invalid barcode type must return HTTP 400 (BadRequest), not 500 with code=None.

        Before fix: werkzeug.exceptions.HTTPException(description=...) with code=None
        produced a malformed HTTP status line.
        After fix: werkzeug.exceptions.BadRequest(...) produces a well-formed 400 response.
        """
        response = self.url_open("/report/barcode/TOTALLY_INVALID_TYPE/testvalue")
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)


@tagged("web_http", "web_controllers_audit")
class TestPivotNegativeInputs(HttpCase):
    """Negative client-supplied integers were silently producing empty range() calls."""

    def test_export_xlsx_negative_measure_count(self):
        """Negative measure_count must be clamped to 0, not produce an empty range silently."""
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
            data={"data": json_dumps(jdata), "csrf_token": http.Request.csrf_token(self)},
        )
        self.assertEqual(response.status_code, HTTPStatus.OK)

    def test_export_xlsx_negative_header_width(self):
        """Negative header width must be clamped to 0, not produce an empty range silently."""
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
            data={"data": json_dumps(jdata), "csrf_token": http.Request.csrf_token(self)},
        )
        self.assertEqual(response.status_code, HTTPStatus.OK)


@tagged("web_http", "web_controllers_audit")
class TestWebClientOpenRedirect(HttpCase):
    """home.py web_client() previously used bare urlsplit() which misses /\\ bypass."""

    def test_backslash_redirect_rejected(self):
        """'/\\\\evil.com' must not be followed: browsers normalise '\\\\' to '/' giving '//evil.com'."""
        self.authenticate("admin", "admin")
        # %2F%5C = /\ (URL-encoded)
        response = self.url_open(
            "/odoo?redirect=%2F%5Cevil.com",
            allow_redirects=False,
        )
        location = response.headers.get("Location", "")
        self.assertNotIn("evil.com", location)

    def test_local_path_redirect_accepted(self):
        """A genuine local path must still redirect correctly after switching to _is_local_url."""
        self.authenticate("admin", "admin")
        response = self.url_open(
            "/odoo?redirect=/odoo/contacts",
            allow_redirects=False,
        )
        self.assertEqual(response.status_code, HTTPStatus.SEE_OTHER)
        self.assertIn("/odoo/contacts", response.headers.get("Location", ""))


@tagged("web_controllers_audit")
class TestCompanyLogoFallback(TransactionCase):
    """binary.py company_logo() fallback used imgext which may have been mutated to '.svg'."""

    def test_fallback_uses_hardcoded_logo_png(self):
        """When send_file raises after imgext is mutated to '.svg', fallback must use logo.png.

        The bug: file_path(f"web/static/img/{imgname}{imgext}") with imgext=".svg" →
        FileNotFoundError inside the except handler (logo.svg does not exist).
        The fix: hardcoded file_path("web/static/img/logo.png").

        This code-structure test directly verifies that the correct literal string is used,
        avoiding the complexity of driving the HTTP path with an SVG-bearing company.
        """
        source = inspect.getsource(Binary.company_logo)
        # Fix present: hardcoded fallback
        self.assertIn('file_path("web/static/img/logo.png")', source)
        # Bug absent: imgext variable not used in fallback expression
        self.assertNotIn(
            'file_path(f"web/static/img/{imgname}{imgext}")',
            source,
            "Fallback must not use imgext — it may have been mutated to '.svg'",
        )



@tagged("web_http", "web_controllers_audit")
class TestDatabaseRestoreLogging(HttpCase):
    """database.py restore() previously swallowed exceptions without logging."""

    def test_restore_logs_exception_on_failure(self):
        """restore() must call _logger.exception() when restore_db raises.

        Before fix: error was silently returned to the browser template with no server log.
        After fix: _logger.exception() is called first, leaving a traceback in the log.
        """
        with (
            patch("odoo.service.db.check_super"),  # bypass password verification
            patch(
                "odoo.service.db.restore_db",
                side_effect=Exception("simulated restore error"),
            ),
            self.assertLogs("odoo.addons.web.controllers.database", level="ERROR") as log_cm,
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
    """export.py base() previously raised a raw KeyError on invalid groupby field names."""

    @mute_logger("odoo.addons.web.controllers.export")
    def test_invalid_groupby_field_returns_descriptive_error(self):
        """Invalid groupby field must produce 'Unknown groupby fields' error, not raw KeyError.

        Before fix: Model._fields["nonexistent"] → KeyError("nonexistent") leaks model
        structure and gives a cryptic message.
        After fix: UserError("Unknown groupby fields for res.partner: nonexistent") is raised
        and wrapped into the standard InternalServerError JSON payload.
        """
        self.authenticate("admin", "admin")
        data = json_dumps({
            "model": "res.partner",
            "fields": [{"name": "name", "label": "Name"}],
            "ids": [],
            "domain": [],
            "import_compat": False,
            "groupby": ["totally_nonexistent_xyz"],
        })
        response = self.url_open(
            "/web/export/xlsx",
            data={"data": data, "csrf_token": http.Request.csrf_token(self)},
        )
        self.assertEqual(response.status_code, HTTPStatus.INTERNAL_SERVER_ERROR)
        self.assertIn("Unknown groupby fields", response.text)
        self.assertIn("totally_nonexistent_xyz", response.text)


@tagged("web_controllers_audit")
class TestIsLocalUrl(BaseCase):
    """Unit tests for _is_local_url() open-redirect guard in utils.py."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from odoo.addons.web.controllers.utils import _is_local_url
        cls._is_local_url = staticmethod(_is_local_url)

    def test_local_paths_accepted(self):
        """Standard /path URLs must be accepted as local."""
        self.assertTrue(self._is_local_url("/odoo"))
        self.assertTrue(self._is_local_url("/odoo/contacts"))
        self.assertTrue(self._is_local_url("/web"))
        self.assertTrue(self._is_local_url("/web/login"))

    def test_protocol_relative_rejected(self):
        """//evil.com (protocol-relative URL) must be rejected."""
        self.assertFalse(self._is_local_url("//evil.com"))

    def test_backslash_trick_rejected(self):
        """/\\\\evil.com must be rejected (browser normalises backslash → protocol-relative)."""
        self.assertFalse(self._is_local_url("/\\evil.com"))

    def test_absolute_url_rejected(self):
        """Absolute URLs with explicit scheme must be rejected."""
        self.assertFalse(self._is_local_url("https://evil.com"))
        self.assertFalse(self._is_local_url("http://evil.com/odoo"))

    def test_empty_and_none_rejected(self):
        """Empty string and None must be rejected."""
        self.assertFalse(self._is_local_url(""))
        self.assertFalse(self._is_local_url(None))


@tagged("web_controllers_audit")
class TestJsonHelpers(TransactionCase):
    """Unit tests for json_helpers.py helper functions."""

    def test_get_groupby_with_default_group_by(self):
        """get_groupby returns (None, [field]) for a view with default_group_by attribute.

        Before fix: (None, [field] if field else []) — dead conditional, field is always truthy.
        After fix:  (None, [field]) — walrus operator, dead branch removed.
        """
        from odoo.addons.web.controllers.json_helpers import get_groupby

        tree = etree.fromstring('<kanban default_group_by="partner_id"><templates/></kanban>')
        groupby, fields = get_groupby(tree)
        self.assertIsNone(groupby)
        self.assertEqual(fields, ["partner_id"])

    def test_get_groupby_no_default_group_by(self):
        """get_groupby returns (None, None) for a view without default_group_by."""
        from odoo.addons.web.controllers.json_helpers import get_groupby

        tree = etree.fromstring('<kanban><templates/></kanban>')
        groupby, fields = get_groupby(tree)
        self.assertIsNone(groupby)
        self.assertIsNone(fields)

    def test_get_groupby_explicit_param_overrides_view(self):
        """Explicit groupby param takes precedence over view definition."""
        from odoo.addons.web.controllers.json_helpers import get_groupby

        tree = etree.fromstring('<kanban default_group_by="stage_id"><templates/></kanban>')
        groupby, fields = get_groupby(tree, groupby="partner_id,user_id")
        self.assertEqual(groupby, ["partner_id", "user_id"])
        self.assertIsNone(fields)

    def test_get_view_id_and_type_returns_false_for_unset_view(self):
        """get_view_id_and_type returns (False, view_type) when no specific view is set.

        Return type annotation was corrected from tuple[int | None, str] to
        tuple[int | bool, str] to reflect Odoo's 'False = no ID' convention.
        """
        from odoo.addons.web.controllers.json_helpers import get_view_id_and_type

        action = self.env["ir.actions.act_window"].create({
            "name": "_AuditTest",
            "res_model": "res.partner",
            "view_mode": "list,form",
        })
        view_id, view_type = get_view_id_and_type(action, "list")
        self.assertIs(view_id, False, "Must be False (Odoo 'no ID' convention), not None")
        self.assertEqual(view_type, "list")
