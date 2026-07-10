"""Regression coverage for ir.actions.report's WeasyPrint URL fetcher.

Audit finding IAR-T2: the OdooURLFetcher path-traversal guard
(_resolve_static_file) and the _parse_image_url parser were untested.
"""

import io
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

import requests
from weasyprint.urls import URLFetcher

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

from odoo.addons.base.models.ir_actions_report import (
    PDF_OPTIONS_DATA_KEY,
    OdooURLFetcher,
    _is_blocked_fetch_ip,
)


@tagged("post_install", "-at_install")
class TestReportUrlFetcher(TransactionCase):
    """Lock the OdooURLFetcher static-file guard and image-URL parser."""

    def setUp(self):
        super().setUp()
        self.report = self.env["ir.actions.report"]
        # Outside an HTTP request _setup_session() is a no-op, so the fetcher is
        # safe to build and inspect directly in a TransactionCase.
        self.fetcher = self.report._build_url_fetcher()
        self.addCleanup(self.fetcher.cleanup)

    @mute_logger("odoo.addons.base.models.ir_actions_report")
    def test_static_file_rejects_path_traversal(self):
        """A ``../``-escaping static path resolves to nothing (no escape)."""
        # The is_relative_to() guard rejects any candidate resolving outside the
        # addons root, so traversal yields None instead of leaking a file.
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
        # No regex matches and the query lacks an id, so res_id is 0 and raises.
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
    """Regression coverage for ir.actions.report audit fixes: create_action
    access check, _search_model_id fallback, single ref resolution per render,
    unknown-report_type error, and the barcode Code128 fallback."""

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


@tagged("post_install", "-at_install")
class TestReportAttachmentNameCache(TransactionCase):
    """_prepare_pdf_report_attachment_vals_list must consume the
    "attachment_name" cache written by _render_qweb_pdf_prepare_streams and
    only fall back to safe_eval for entries that lack it (overridden
    prepare_streams)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Audit Attach"})
        cls.report = cls.env["ir.actions.report"].create(
            {
                "name": "audit attach report",
                "model": "res.partner",
                "report_type": "qweb-pdf",
                "report_name": "base.audit_attach_report_dummy",
                "attachment": "'fallback-%s.pdf' % object.id",
            }
        )

    def _stream_entry(self, **extra):
        return {"stream": io.BytesIO(b"%PDF-audit"), "attachment": None, **extra}

    def test_cached_attachment_name_skips_safe_eval(self):
        # Poison the expression: any safe_eval would raise, so getting a vals
        # list back proves the cached name was used instead.
        self.report.attachment = "1/0"
        streams = {self.partner.id: self._stream_entry(attachment_name="cached.pdf")}
        vals_list = self.env[
            "ir.actions.report"
        ]._prepare_pdf_report_attachment_vals_list(self.report, streams)
        self.assertEqual(len(vals_list), 1)
        self.assertEqual(vals_list[0]["name"], "cached.pdf")
        self.assertEqual(vals_list[0]["res_id"], self.partner.id)

    def test_evaluated_empty_cache_skips_attachment(self):
        # "" is the evaluated-and-empty sentinel: no attachment, no re-eval.
        self.report.attachment = "1/0"
        streams = {self.partner.id: self._stream_entry(attachment_name="")}
        vals_list = self.env[
            "ir.actions.report"
        ]._prepare_pdf_report_attachment_vals_list(self.report, streams)
        self.assertEqual(vals_list, [])

    def test_missing_cache_falls_back_to_safe_eval(self):
        # Entries built by an overridden prepare_streams lack the key: the
        # documented None sentinel must trigger the safe_eval fallback.
        for entry in (self._stream_entry(), self._stream_entry(attachment_name=None)):
            with self.subTest(entry=entry):
                vals_list = self.env[
                    "ir.actions.report"
                ]._prepare_pdf_report_attachment_vals_list(
                    self.report, {self.partner.id: entry}
                )
                self.assertEqual(len(vals_list), 1)
                self.assertEqual(
                    vals_list[0]["name"], f"fallback-{self.partner.id}.pdf"
                )


@tagged("post_install", "-at_install")
class TestPdfOptionsChannel(TransactionCase):
    """Native PDF options travel ONLY under data[PDF_OPTIONS_DATA_KEY]: the
    namespaced key is popped before the QWeb context, and legacy top-level
    keys are plain template data, never interpreted as options."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Audit PdfOpts"})
        cls.report = cls.env["ir.actions.report"].create(
            {
                "name": "audit pdfopts report",
                "model": "res.partner",
                "report_type": "qweb-pdf",
                "report_name": "base.audit_pdfopts_report_dummy",
            }
        )

    def _prepare_streams(self, data):
        captured = {}
        registry_cls = type(self.env["ir.actions.report"])
        partner_id = self.partner.id

        def fake_render_qweb_html(model, report_ref, docids, data=None):
            captured["qweb_data"] = data
            return (b"<html/>", "html")

        def fake_prepare_weasyprint_html(model, html, report_model=False):
            return (["<html/>"], [partner_id], {})

        def fake_render_html_to_pdf(
            model,
            bodies,
            report_ref=False,
            landscape=False,
            specific_paperformat_args=None,
            _split=False,
            **kwargs,
        ):
            captured["pdf_kwargs"] = kwargs
            return [b"%PDF-audit"] * len(bodies) if _split else b"%PDF-audit"

        with (
            patch.object(registry_cls, "_render_qweb_html", fake_render_qweb_html),
            patch.object(
                registry_cls,
                "_prepare_weasyprint_html",
                fake_prepare_weasyprint_html,
            ),
            patch.object(registry_cls, "_render_html_to_pdf", fake_render_html_to_pdf),
        ):
            self.env["ir.actions.report"]._render_qweb_pdf_prepare_streams(
                self.report, data, res_ids=[self.partner.id]
            )
        return captured

    def test_namespaced_key_feeds_options_and_is_popped(self):
        captured = self._prepare_streams(
            {PDF_OPTIONS_DATA_KEY: {"pdf_variant": "pdf/a-3b"}}
        )
        self.assertEqual(captured["pdf_kwargs"], {"pdf_variant": "pdf/a-3b"})
        self.assertNotIn(
            PDF_OPTIONS_DATA_KEY,
            captured["qweb_data"],
            "the reserved key must never reach the QWeb rendering context",
        )

    def test_top_level_keys_are_not_options(self):
        captured = self._prepare_streams({"pdf_variant": "pdf/a-3b"})
        self.assertEqual(
            captured["pdf_kwargs"],
            {},
            "legacy top-level data keys must not be interpreted as PDF options",
        )


@tagged("post_install", "-at_install")
class TestReportRenderEntryPoints(TransactionCase):
    """Entry-point argument normalization (single _normalize_render_args) and
    the report_action docids contract."""

    def test_render_qweb_html_accepts_int_docids(self):
        module = self.env["ir.module.module"].search([("name", "=", "base")])
        content, report_type = self.env["ir.actions.report"]._render_qweb_html(
            "base.report_irmodulereference", module.id
        )
        self.assertEqual(report_type, "html")
        self.assertTrue(content)

    def test_render_qweb_html_does_not_mutate_caller_data(self):
        module = self.env["ir.module.module"].search([("name", "=", "base")])
        data = {}
        self.env["ir.actions.report"]._render_qweb_html(
            "base.report_irmodulereference", [module.id], data=data
        )
        self.assertEqual(data, {}, "the caller's data dict must not be mutated")

    def test_report_action_accepts_any_id_iterable(self):
        report = self.env.ref("base.ir_module_reference_print")
        action = report.report_action((7, 9), config=False)
        self.assertEqual(action["context"]["active_ids"], [7, 9])

    def test_report_action_rejects_non_iterable_docids(self):
        report = self.env.ref("base.ir_module_reference_print")
        with self.assertRaises(TypeError):
            report.report_action(3.5, config=False)


@tagged("post_install", "-at_install")
class TestValidActionReportsDomainGuard(TransactionCase):
    """get_valid_action_reports is a public RPC feeding the action menu: one
    malformed stored domain must not 500 the menu for the whole model."""

    def test_malformed_domain_is_logged_and_treated_valid(self):
        Report = self.env["ir.actions.report"]
        common = {
            "model": "res.partner",
            "report_type": "qweb-pdf",
        }
        good = Report.create(
            {
                "name": "audit good domain",
                "report_name": "base.audit_good_domain_dummy",
                "domain": "[('name', '=', 'Audit Domain Guard')]",
                **common,
            }
        )
        bad = Report.create(
            {
                "name": "audit bad domain",
                "report_name": "base.audit_bad_domain_dummy",
                "domain": "[('name' =",
                **common,
            }
        )
        partner = self.env["res.partner"].create({"name": "Audit Domain Guard"})
        with self.assertLogs(
            "odoo.addons.base.models.ir_actions_report", level="WARNING"
        ) as capture:
            valid_ids = (good + bad).get_valid_action_reports(
                "res.partner", [partner.id]
            )
        self.assertIn(good.id, valid_ids)
        self.assertIn(bad.id, valid_ids, "a malformed domain degrades to always-valid")
        self.assertTrue(any("malformed domain" in line for line in capture.output))


@tagged("post_install", "-at_install")
class TestWeasyPrintFailureObservability(TransactionCase):
    """WeasyPrint failure paths keep the traceback in the server log while the
    user still gets a clean UserError."""

    def test_layout_failure_logs_traceback(self):
        engine = self.env["ir.actions.report"]._build_weasyprint_engine()
        with (
            patch(
                "odoo.addons.base.models.ir_actions_report.weasyprint.HTML",
                side_effect=ValueError("audit-layout-boom"),
            ),
            self.assertLogs(
                "odoo.addons.base.models.ir_actions_report", level="ERROR"
            ) as capture,
            self.assertRaises(UserError),
        ):
            engine._render_body_document("<html/>", fetcher=None, body_css=[])
        self.assertTrue(
            any(record.exc_info for record in capture.records),
            "the log record must carry the traceback (exc_info=True)",
        )


@tagged("post_install", "-at_install")
class TestHtmlToImageTestMode(TransactionCase):
    """_render_html_to_image honors force_report_rendering, mirroring the PDF
    path's test-mode contract."""

    def test_short_circuits_in_test_mode(self):
        registry_cls = type(self.env["ir.actions.report"])
        with patch.object(
            registry_cls,
            "_build_url_fetcher",
            side_effect=AssertionError("must not render in test mode"),
        ) as fetcher_mock:
            result = self.env["ir.actions.report"]._render_html_to_image(
                ["<div>audit</div>"], 10, 10
            )
        self.assertEqual(result, [None])
        self.assertFalse(fetcher_mock.called)

    def test_force_report_rendering_bypasses_short_circuit(self):
        registry_cls = type(self.env["ir.actions.report"])
        fetcher_cm = MagicMock()
        fetcher_cm.__enter__ = MagicMock(return_value=MagicMock())
        fetcher_cm.__exit__ = MagicMock(return_value=False)
        with (
            patch.object(
                registry_cls, "_build_url_fetcher", return_value=fetcher_cm
            ) as fetcher_mock,
            patch(
                "odoo.addons.base.models.ir_actions_report.weasyprint.HTML",
                side_effect=ValueError("audit-image-boom"),
            ),
            self.assertLogs(
                "odoo.addons.base.models.ir_actions_report", level="WARNING"
            ),
        ):
            result = (
                self.env["ir.actions.report"]
                .with_context(force_report_rendering=True)
                ._render_html_to_image(["<div>audit</div>"], 10, 10)
            )
        # The per-body failure degrades to None, but the pipeline ran: the
        # fetcher was built instead of the test-mode early return.
        self.assertEqual(result, [None])
        self.assertTrue(fetcher_mock.called)


@tagged("post_install", "-at_install")
class TestFetcherHttpFallback(TransactionCase):
    """OdooURLFetcher._fetch_via_http retries the stock WeasyPrint fetcher
    with the absolute URL (a relative path is unresolvable there) and the
    local barcode fast path forwards every option the HTTP route accepts."""

    def setUp(self):
        super().setUp()
        self.fetcher = self.env["ir.actions.report"]._build_url_fetcher()
        self.addCleanup(self.fetcher.cleanup)

    @mute_logger("odoo.addons.base.models.ir_actions_report")
    def test_http_fallback_retries_with_full_url(self):
        seen = {}

        def failing_get(url, cookies):
            raise requests.exceptions.ConnectionError("audit: primary down")

        def fake_super_fetch(fetcher_self, url, headers=None):
            seen["url"] = url
            raise ValueError("audit: stop here")

        with (
            patch.object(OdooURLFetcher, "_do_get", staticmethod(failing_get)),
            patch.object(URLFetcher, "fetch", fake_super_fetch),
            self.assertRaises(ValueError),
        ):
            self.fetcher._fetch_via_http("/web/image/1", "/web/image/1")
        parsed = urlparse(seen["url"])
        self.assertTrue(
            parsed.scheme and parsed.netloc,
            f"fallback must receive an absolute URL, got {seen['url']!r}",
        )
        self.assertTrue(seen["url"].endswith("/web/image/1"))

    def test_resolve_barcode_forwards_barborder(self):
        captured = {}
        registry_cls = type(self.env["ir.actions.report"])

        def fake_barcode(model, barcode_type, value, **kwargs):
            captured["type"] = barcode_type
            captured.update(kwargs)
            return b"\x89PNG-audit"

        with patch.object(registry_cls, "barcode", fake_barcode):
            response = self.fetcher._resolve_barcode(
                "/report/barcode/QR/audit?barBorder=0",
                "/report/barcode/QR/audit",
                "barBorder=0&quiet=1",
            )
        self.assertIsNotNone(response)
        self.assertEqual(captured["type"], "QR")
        self.assertEqual(captured.get("barBorder"), "0")
        self.assertEqual(captured.get("quiet"), "1")
