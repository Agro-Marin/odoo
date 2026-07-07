"""Regression coverage for ir.actions.report's WeasyPrint URL fetcher.

Audit Tranche 4, finding IAR-T2: the OdooURLFetcher path-traversal guard
(_resolve_static_file) and the _parse_image_url URL parser were entirely
untested. These tests lock the current behaviour of both helpers.
"""

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

from odoo.addons.base.models.ir_actions_report import _is_blocked_fetch_ip


@tagged("post_install", "-at_install")
class TestReportUrlFetcher(TransactionCase):
    """Lock the OdooURLFetcher static-file guard and image-URL parser."""

    def setUp(self):
        """Build a fetcher instance via the model's public factory."""
        super().setUp()
        self.report = self.env["ir.actions.report"]
        # _build_url_fetcher() returns an OdooURLFetcher; outside an HTTP
        # request _setup_session() is a no-op, so the instance is safe to
        # build and inspect directly in a TransactionCase.
        self.fetcher = self.report._build_url_fetcher()
        self.addCleanup(self.fetcher.cleanup)

    @mute_logger("odoo.addons.base.models.ir_actions_report")
    def test_static_file_rejects_path_traversal(self):
        """A ``../``-escaping static path resolves to nothing (no escape)."""
        # The is_relative_to() guard must reject any candidate that resolves
        # outside the addons root, so a traversal attempt yields None rather
        # than leaking a file from a sibling/parent directory.
        url = "http://localhost/base/static/../../../../../../etc/passwd"
        path = "/base/static/../../../../../../etc/passwd"
        self.assertIsNone(self.fetcher._resolve_static_file(url, path))

    def test_static_file_ignores_non_static_path(self):
        """A path whose 2nd segment is not ``static`` is skipped early."""
        # Guard at the top of _resolve_static_file: parts[1] must be "static".
        self.assertIsNone(
            self.fetcher._resolve_static_file(
                "http://localhost/base/models/foo.py", "/base/models/foo.py"
            )
        )
        # Fewer than 3 segments is also rejected.
        self.assertIsNone(
            self.fetcher._resolve_static_file("http://localhost/base", "/base")
        )

    def test_parse_image_url_variants(self):
        """Table-drive _parse_image_url across its three resolution regexes."""
        cases = [
            # model/id/field, no dimensions -> width/height default to 0
            (
                "/web/image/res.partner/42/image_1920",
                "",
                ("res.partner", 42, "image_1920", 0, 0),
            ),
            # model/id/field with WxH dimensions
            (
                "/web/image/res.partner/42/image_128/64x96",
                "",
                ("res.partner", 42, "image_128", 64, 96),
            ),
            # bare id -> defaults to ir.attachment / raw field
            (
                "/web/image/7",
                "",
                ("ir.attachment", 7, "raw", 0, 0),
            ),
            # bare id with a unique suffix and dimensions
            (
                "/web/image/7-deadbeef/20x30",
                "",
                ("ir.attachment", 7, "raw", 20, 30),
            ),
            # query-string fallback when the path matches no regex
            (
                "/web/image",
                "model=res.users&id=3&field=avatar_128&width=10&height=15",
                ("res.users", 3, "avatar_128", 10, 15),
            ),
            # query-string fallback with only an id -> model/field defaults
            (
                "/web/image",
                "id=9",
                ("ir.attachment", 9, "raw", 0, 0),
            ),
        ]
        for path, query, expected in cases:
            with self.subTest(path=path, query=query):
                self.assertEqual(self.fetcher._parse_image_url(path, query), expected)

    def test_parse_image_url_missing_id_raises(self):
        """The query-string fallback raises ValueError when no id is given."""
        # No regex matches the path and the query lacks an id, so res_id is 0
        # and the guard raises ValueError.
        with self.assertRaises(ValueError):
            self.fetcher._parse_image_url("/web/image", "model=res.partner")

    def test_blocked_fetch_ip_classification(self):
        """_is_blocked_fetch_ip flags private/reserved IP literals, not hosts."""
        # SSRF pivot targets — must all be blocked.
        for host in (
            "169.254.169.254",  # cloud metadata endpoint (link-local)
            "127.0.0.2",  # loopback outside _LOOPBACK_HOSTS
            "10.1.2.3",
            "192.168.0.5",
            "172.16.9.9",  # RFC 1918
            "0.0.0.0",  # unspecified
            "::1",  # IPv6 loopback
            "fe80::1",  # IPv6 link-local
        ):
            with self.subTest(host=host):
                self.assertTrue(_is_blocked_fetch_ip(host))
        # Public IPs and real hostnames must pass through (rendered as-is).
        for host in ("8.8.8.8", "93.184.216.34", "cdn.example.com", None, ""):
            with self.subTest(host=host):
                self.assertFalse(_is_blocked_fetch_ip(host))

    @mute_logger("odoo.addons.base.models.ir_actions_report")
    def test_fetch_refuses_private_ip(self):
        """fetch() refuses an absolute URL pointing at a private/reserved IP."""
        # WeasyPrint treats a raising fetch() as a missing resource, so raising
        # here degrades the report gracefully instead of performing the SSRF.
        with self.assertRaises(ValueError):
            self.fetcher.fetch("http://169.254.169.254/latest/meta-data/")

    def test_fetch_rejects_file_scheme(self):
        """file:// is not in allowed_protocols, so local-file reads are refused."""
        # Guards against the wkhtmltopdf-style file:///etc/passwd disclosure.
        with self.assertRaises(ValueError):
            self.fetcher.fetch("file:///etc/passwd")


@tagged("post_install", "-at_install")
class TestReportAuditFixes(TransactionCase):
    """Regression coverage for the ir.actions.report audit fixes: batched
    create_action with access check, _search_model_id fallback protocol,
    single report-reference resolution per render, unknown-report_type error,
    and the observable barcode Code128 fallback.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reports = cls.env["ir.actions.report"].create(
            [
                {
                    "name": "Audit Report 1",
                    "model": "res.partner",
                    "report_name": "base.audit_report_1",
                },
                {
                    "name": "Audit Report 2",
                    "model": "res.partner",
                    "report_name": "base.audit_report_2",
                },
                {
                    "name": "Audit Report 3",
                    "model": "res.users",
                    "report_name": "base.audit_report_3",
                },
            ]
        )

    def test_create_action_binds_per_model(self):
        """create_action must bind every report, grouped per model."""
        self.reports.create_action()
        partner_model = self.env["ir.model"]._get("res.partner")
        users_model = self.env["ir.model"]._get("res.users")
        self.assertEqual(self.reports[0].binding_model_id, partner_model)
        self.assertEqual(self.reports[1].binding_model_id, partner_model)
        self.assertEqual(self.reports[2].binding_model_id, users_model)
        self.assertEqual(set(self.reports.mapped("binding_type")), {"report"})

    def test_create_action_checks_write_access(self):
        """Like unlink_action (and the ir.actions.server twin), create_action
        must be denied to users without write access on the report."""
        user = self.env["res.users"].create(
            {
                "name": "Report Audit User",
                "login": "report_audit_user",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        with self.assertRaises(AccessError):
            self.reports.with_user(user).create_action()

    def test_search_model_id_unhandled_combo_returns_notimplemented(self):
        """An operator/value combo no branch handles must return
        NotImplemented (generic ORM fallback), not silently match nothing."""
        Report = self.env["ir.actions.report"]
        self.assertIs(Report._search_model_id("=", None), NotImplemented)
        # Handled combos still produce a usable domain.
        partner_model = self.env["ir.model"]._get("res.partner")
        found = Report.search([("model_id", "=", partner_model.id)])
        self.assertIn(self.reports[0], found)

    def test_render_unknown_report_type_raises(self):
        """_render must raise a UserError naming the type, not return None."""
        report = self.reports[0]
        # The selection constraint is ORM-level only; force a bogus type the
        # way a corrupt row would present it.
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE ir_act_report_xml SET report_type = %s WHERE id = %s",
            ["qweb-bogus", report.id],
        )
        report.invalidate_recordset(["report_type"])
        with self.assertRaises(UserError) as capture:
            self.env["ir.actions.report"]._render(report, [])
        self.assertIn("qweb-bogus", str(capture.exception))

    def test_render_resolves_string_reference_once(self):
        """A string report_ref must hit the report_name search once per
        render; internal calls receive the resolved record."""
        self.env["ir.actions.report"].create(
            {
                "name": "Audit Render Report",
                "model": "res.partner",
                "report_type": "qweb-html",
                "report_name": "base.audit_report_render",
            }
        )
        self.env["ir.ui.view"].create(
            {
                "type": "qweb",
                "name": "base.audit_report_render",
                "key": "base.audit_report_render",
                "arch": '<main><div class="article"><span>audit</span></div></main>',
            }
        )
        Report = self.env["ir.actions.report"]
        report_cls = type(Report)
        original_get_report = report_cls._get_report
        seen_refs = []

        def _tracking_get_report(model_self, report_ref):
            seen_refs.append(report_ref)
            return original_get_report(model_self, report_ref)

        self.patch(report_cls, "_get_report", _tracking_get_report)
        content, report_type = Report._render(
            "base.audit_report_render", [self.env.user.partner_id.id]
        )
        self.assertEqual(report_type, "html")
        self.assertIn(b"audit", content)
        string_refs = [ref for ref in seen_refs if isinstance(ref, str)]
        self.assertEqual(
            len(string_refs),
            1,
            "the string report reference must be resolved exactly once per render",
        )

    def test_barcode_fallback_to_code128_logs_warning(self):
        """The Code128 fallback must log the original failure (observability)
        while still producing a valid PNG."""
        with self.assertLogs(
            "odoo.addons.base.models.ir_actions_report", level="WARNING"
        ) as capture:
            # I2of5 only accepts digits: the drawing call raises ValueError,
            # which must degrade to a Code128 rendering of the same value.
            png = self.env["ir.actions.report"].barcode("I2of5", "not-numeric")
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertTrue(
            any("falling back to Code128" in line for line in capture.output)
        )

    def test_report_name_is_indexed(self):
        """report_name is searched on every string-ref resolution: keep it
        btree-indexed."""
        self.assertTrue(self.env["ir.actions.report"]._fields["report_name"].index)
