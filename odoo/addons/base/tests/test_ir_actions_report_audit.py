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
    _is_blocked_fetch_host,
)


@tagged("post_install", "-at_install")
class TestReportUrlFetcher(TransactionCase):
    def setUp(self):
        super().setUp()
        self.report = self.env["ir.actions.report"]
        self.fetcher = self.report._build_url_fetcher()
        self.addCleanup(self.fetcher.cleanup)

    @mute_logger("odoo.addons.base.models.ir_actions_report")
    def test_static_file_rejects_path_traversal(self):
        url = "http://localhost/base/static/../../../../../../etc/passwd"
        path = "/base/static/../../../../../../etc/passwd"
        self.assertIsNone(self.fetcher._resolve_static_file(url, path))

    def test_static_file_ignores_non_static_path(self):
        self.assertIsNone(
            self.fetcher._resolve_static_file(
                "http://localhost/base/models/foo.py", "/base/models/foo.py"
            )
        )
        self.assertIsNone(
            self.fetcher._resolve_static_file("http://localhost/base", "/base")
        )

    def test_parse_image_url_variants(self):
        cases = [
            (
                "/web/image/res.partner/42/image_1920",
                "",
                ("res.partner", 42, "image_1920", 0, 0),
            ),
            (
                "/web/image/res.partner/42/image_128/64x96",
                "",
                ("res.partner", 42, "image_128", 64, 96),
            ),
            (
                "/web/image/7",
                "",
                ("ir.attachment", 7, "raw", 0, 0),
            ),
            (
                "/web/image/7-deadbeef/20x30",
                "",
                ("ir.attachment", 7, "raw", 20, 30),
            ),
            (
                "/web/image",
                "model=res.users&id=3&field=avatar_128&width=10&height=15",
                ("res.users", 3, "avatar_128", 10, 15),
            ),
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
        with self.assertRaises(ValueError):
            self.fetcher._parse_image_url("/web/image", "model=res.partner")

    def test_blocked_fetch_host_classification(self):
        for host in (
            "169.254.169.254",
            "127.0.0.2",
            "10.1.2.3",
            "192.168.0.5",
            "172.16.9.9",
            "0.0.0.0",
            "::1",
            "fe80::1",
        ):
            with self.subTest(host=host):
                self.assertTrue(_is_blocked_fetch_host(host))
        for host in ("8.8.8.8", "93.184.216.34", "cdn.example.com", None, ""):
            with self.subTest(host=host):
                self.assertFalse(_is_blocked_fetch_host(host))

    def test_loopback_names_are_blocked_without_resolving(self):
        for host in (
            "localhost",
            "LOCALHOST",
            "ip6-localhost",
            "ip6-loopback",
            "db.localhost",
            "localhost.",
            "db.localhost.",
        ):
            with self.subTest(host=host):
                self.assertTrue(_is_blocked_fetch_host(host))

    def test_names_needing_resolution_stay_unblocked(self):
        for host in ("localtest.me", "internal.corp.example.com"):
            with self.subTest(host=host):
                self.assertFalse(_is_blocked_fetch_host(host))

    @mute_logger("odoo.addons.base.models.ir_actions_report")
    def test_fetch_refuses_private_ip(self):
        with self.assertRaises(ValueError):
            self.fetcher.fetch("http://169.254.169.254/latest/meta-data/")

    def test_fetch_rejects_file_scheme(self):
        with self.assertRaises(ValueError):
            self.fetcher.fetch("file:///etc/passwd")


@tagged("post_install", "-at_install")
class TestReportAuditFixes(TransactionCase):
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
        self.reports.create_action()
        partner_model = self.env["ir.model"]._get("res.partner")
        users_model = self.env["ir.model"]._get("res.users")
        self.assertEqual(self.reports[0].binding_model_id, partner_model)
        self.assertEqual(self.reports[1].binding_model_id, partner_model)
        self.assertEqual(self.reports[2].binding_model_id, users_model)
        self.assertEqual(set(self.reports.mapped("binding_type")), {"report"})

    def test_create_action_checks_write_access(self):
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
        Report = self.env["ir.actions.report"]
        self.assertIs(Report._search_model_id("=", None), NotImplemented)
        partner_model = self.env["ir.model"]._get("res.partner")
        found = Report.search([("model_id", "=", partner_model.id)])
        self.assertIn(self.reports[0], found)

    def test_render_unknown_report_type_raises(self):
        report = self.reports[0]
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
        with self.assertLogs(
            "odoo.addons.base.models.ir_actions_report", level="WARNING"
        ) as capture:
            png = self.env["ir.actions.report"].barcode("I2of5", "not-numeric")
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertTrue(
            any("falling back to Code128" in line for line in capture.output)
        )

    def test_report_name_is_indexed(self):
        self.assertTrue(self.env["ir.actions.report"]._fields["report_name"].index)


@tagged("post_install", "-at_install")
class TestReportAttachmentNameCache(TransactionCase):
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
        self.report.attachment = "1/0"
        streams = {self.partner.id: self._stream_entry(attachment_name="cached.pdf")}
        vals_list = self.env[
            "ir.actions.report"
        ]._prepare_pdf_report_attachment_vals_list(self.report, streams)
        self.assertEqual(len(vals_list), 1)
        self.assertEqual(vals_list[0]["name"], "cached.pdf")
        self.assertEqual(vals_list[0]["res_id"], self.partner.id)

    def test_evaluated_empty_cache_skips_attachment(self):
        self.report.attachment = "1/0"
        streams = {self.partner.id: self._stream_entry(attachment_name="")}
        vals_list = self.env[
            "ir.actions.report"
        ]._prepare_pdf_report_attachment_vals_list(self.report, streams)
        self.assertEqual(vals_list, [])

    def test_missing_cache_falls_back_to_safe_eval(self):
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
        self.assertEqual(result, [None])
        self.assertTrue(fetcher_mock.called)


@tagged("post_install", "-at_install")
class TestAssociatedViewMissingActionRef(TransactionCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.report = cls.env["ir.actions.report"].create(
            {
                "name": "Audit Associated View Report",
                "model": "res.partner",
                "report_name": "base.audit_associated_view_dummy",
            }
        )

    def test_returns_action_data_when_action_ref_exists(self) -> None:
        data = self.report.associated_view()
        self.assertIsInstance(data, dict)
        matching_view, other_view = self.env["ir.ui.view"].create(
            [
                {"name": "audit_associated_view_dummy", "type": "qweb", "arch": "<t/>"},
                {"name": "audit_unrelated_view", "type": "qweb", "arch": "<t/>"},
            ]
        )
        found = self.env["ir.ui.view"].search(data["domain"])
        self.assertIn(matching_view, found)
        self.assertNotIn(other_view, found)

    def test_returns_false_when_action_ref_missing(self) -> None:
        imd = self.env["ir.model.data"].search(
            [("module", "=", "base"), ("name", "=", "action_ui_view")]
        )
        imd.unlink()
        self.assertFalse(self.report.associated_view())

    def test_returns_false_when_report_name_has_no_module_part(self) -> None:
        self.report.report_name = "audit_no_module_part"
        self.assertFalse(self.report.associated_view())


@tagged("post_install", "-at_install")
class TestXmlidLookupCacheOrderingAfterWrite(TransactionCase):
    def test_db_row_reflects_write_before_cache_clear(self) -> None:
        group_a = self.env["res.groups"].create({"name": "Audit Group A"})
        group_b = self.env["res.groups"].create({"name": "Audit Group B"})
        imd = self.env["ir.model.data"].create(
            {
                "module": "__test_imd_audit",
                "name": "test_group_order",
                "model": "res.groups",
                "res_id": group_a.id,
            }
        )
        self.env.flush_all()

        observed_res_id = []

        def _probe_db_on_clear_cache(*args: object, **kwargs: object) -> None:
            self.env.cr.execute(
                "SELECT res_id FROM ir_model_data WHERE module = %s AND name = %s",
                ["__test_imd_audit", "test_group_order"],
            )
            observed_res_id.append(self.env.cr.fetchone()[0])

        self.patch(self.env.registry, "clear_cache", _probe_db_on_clear_cache)
        imd.write({"res_id": group_b.id})

        self.assertTrue(observed_res_id)
        self.assertEqual(
            observed_res_id,
            [group_b.id] * len(observed_res_id),
            "the DB row must already reflect the write by the time "
            "clear_cache() runs, else a concurrent raw-SQL lookup could "
            "re-cache the pre-write row",
        )


@tagged("post_install", "-at_install")
class TestFetcherHttpFallback(TransactionCase):
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


@tagged("post_install", "-at_install")
class TestReportFetcherOrigin(TransactionCase):
    def _fetcher(self, base_url):
        fetcher = OdooURLFetcher(self.env, base_url=base_url)
        fetcher._session_cookie = "SESSIONSECRET"
        return fetcher

    def _route(self, fetcher, url):
        seen = {}

        def do_get(target, cookies, verify=True):
            seen["local"] = verify
            response = MagicMock()
            response.headers = {"Content-Type": "image/png"}
            response.content = b"x"
            return response

        fetcher._do_get = do_get
        with patch.object(
            URLFetcher, "fetch", lambda self, u, headers=None: MagicMock()
        ):
            fetcher.fetch(url)
        return ("local", seen["local"]) if "local" in seen else ("parent", None)

    def test_cookie_only_reaches_the_exact_origin(self):
        fetcher = self._fetcher("https://erp.example.com")
        self.assertEqual(self._route(fetcher, "/web/content/1"), ("local", True))
        self.assertEqual(
            self._route(fetcher, "https://erp.example.com/web/content/1"),
            ("local", True),
        )
        for foreign in (
            "https://erp.example.com:9999/web/content/1",
            "http://erp.example.com/web/content/1",
            "https://evil.example.net/pixel.png",
        ):
            self.assertEqual(
                self._route(fetcher, foreign),
                ("parent", None),
                f"{foreign} was treated as this database's own origin",
            )
        fetcher.cleanup()

    @mute_logger("odoo.addons.base.models.ir_actions_report")
    def test_loopback_name_is_refused_from_a_public_origin(self):
        fetcher = self._fetcher("https://erp.example.com")
        for target in (
            "http://localhost:8069/web/content/1",
            "http://ip6-localhost:8069/web/content/1",
            "http://db.localhost/web/content/1",
        ):
            with self.subTest(target=target), self.assertRaises(ValueError):
                self._route(fetcher, target)
        fetcher.cleanup()

    def test_tls_verification_is_waived_only_for_loopback(self):
        loopback = self._fetcher("http://localhost:8069")
        self.assertEqual(
            self._route(loopback, "http://localhost:8069/web/content/1"),
            ("local", False),
        )
        loopback.cleanup()

    def test_private_address_literals_stay_refused(self):
        fetcher = self._fetcher("https://erp.example.com")
        with (
            self.assertRaises(ValueError),
            mute_logger("odoo.addons.base.models.ir_actions_report"),
        ):
            self._route(fetcher, "http://169.254.169.254/latest/meta-data/")
        fetcher.cleanup()
