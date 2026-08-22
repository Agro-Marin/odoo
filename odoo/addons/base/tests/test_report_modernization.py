import logging

import odoo.tests

from odoo.addons.base.models.ir_actions_report import (
    PDF_OPTIONS_DATA_KEY,
    _prepare_watermark_css,
    _weasy_warning_capture,
)

ARCH = """
<main>
    <div class="article" data-oe-model="res.partner" t-att-data-oe-id="docs.id">
        <span t-field="docs.display_name" />
    </div>
</main>
"""


@odoo.tests.tagged("post_install", "-at_install")
class TestPdfDocumentMetadata(odoo.tests.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env["ir.actions.report"].create(
            {
                "name": "Partner Sheet",
                "report_name": "base.test_report_metadata",
                "model": "res.partner",
                "print_report_name": "'Sheet-%s' % object.name",
            }
        )
        cls.env["ir.ui.view"].create(
            {
                "type": "qweb",
                "name": "base.test_report_metadata",
                "key": "base.test_report_metadata",
                "arch": ARCH,
            }
        )
        cls.partner = cls.env["res.partner"].create({"name": "Metadata Probe"})

    def _render(self, **ctx):
        report = self.report.with_context(force_report_rendering=True, **ctx)
        pdf, _content_type = report._render_qweb_pdf(self.report.id, [self.partner.id])
        return pdf

    def test_pdf_metadata_from_record_and_company(self):
        import pymupdf

        with pymupdf.open(stream=self._render(), filetype="pdf") as doc:
            metadata = doc.metadata
            lang = doc.xref_get_key(doc.pdf_catalog(), "Lang")
        self.assertEqual(metadata["title"], "Sheet-Metadata Probe")
        self.assertEqual(metadata["author"], self.env.company.display_name)
        self.assertEqual(metadata["creator"], "Odoo")
        self.assertTrue(metadata["creationDate"])
        self.assertEqual(lang, ("string", "en-US"))

    def test_pdf_title_falls_back_to_report_label(self):
        import pymupdf

        self.report.print_report_name = False
        with pymupdf.open(stream=self._render(), filetype="pdf") as doc:
            title = doc.metadata["title"]
        self.assertEqual(title, "Partner Sheet")

    def test_broken_print_report_name_never_blocks_printing(self):
        import pymupdf

        self.report.print_report_name = "object.missing_field_xyz"
        with pymupdf.open(stream=self._render(), filetype="pdf") as doc:
            title = doc.metadata["title"]
        self.assertEqual(title, "Partner Sheet")

    def test_watermark_context_stamps_every_copy(self):
        import pymupdf

        with pymupdf.open(stream=self._render(), filetype="pdf") as doc:
            self.assertNotIn("CONFIDENTIAL", doc[0].get_text())
        stamped = self._render(report_watermark="Confidential")
        with pymupdf.open(stream=stamped, filetype="pdf") as doc:
            self.assertIn("CONFIDENTIAL", doc[0].get_text())


@odoo.tests.tagged("post_install", "-at_install")
class TestWatermarkCss(odoo.tests.TransactionCase):
    def test_watermark_css_escapes_hostile_text(self):
        css = _prepare_watermark_css('a"b\\c\nd')
        self.assertIn('content: "a\\"b\\\\c d";', css)

    def test_watermark_css_is_fixed_overlay(self):
        css = _prepare_watermark_css("DRAFT")
        self.assertIn("position: fixed;", css)
        self.assertIn('content: "DRAFT";', css)


@odoo.tests.tagged("post_install", "-at_install")
class TestPdfImageOptions(odoo.tests.TransactionCase):
    def test_build_pdf_options_image_knobs(self):
        Report = self.env["ir.actions.report"]
        self.assertIsNone(Report._prepare_pdf_options())
        options = Report._prepare_pdf_options(dpi=96, jpeg_quality=80)
        self.assertEqual(options, {"dpi": 96, "jpeg_quality": 80})

    def test_pdf_options_channel_forwards_image_knobs(self):
        report = self.env["ir.actions.report"].create(
            {
                "name": "knob probe",
                "report_name": "base.test_report_knobs",
                "model": "res.partner",
            }
        )
        self.env["ir.ui.view"].create(
            {
                "type": "qweb",
                "name": "base.test_report_knobs",
                "key": "base.test_report_knobs",
                "arch": ARCH,
            }
        )
        captured = {}

        def _render_html_to_pdf(_self, bodies, **kwargs):
            captured.update(kwargs)
            if kwargs.get("_split"):
                return [b"%PDF"] * len(bodies)
            return b"%PDF"

        self.patch(type(report), "_render_html_to_pdf", _render_html_to_pdf)
        report.with_context(
            force_report_rendering=True
        )._render_qweb_pdf_prepare_streams(
            report.id,
            {PDF_OPTIONS_DATA_KEY: {"dpi": 120, "jpeg_quality": 70}},
            [self.env.user.partner_id.id],
        )
        self.assertEqual(captured.get("dpi"), 120)
        self.assertEqual(captured.get("jpeg_quality"), 70)


@odoo.tests.tagged("post_install", "-at_install")
class TestWeasyWarningCapture(odoo.tests.TransactionCase):
    def test_capture_collects_and_restores_level(self):
        logger = logging.getLogger("weasyprint")
        level_before = logger.level
        sink = []
        with _weasy_warning_capture.capture(sink):
            self.assertEqual(logger.level, logging.WARNING)
            logger.warning("Ignored `bogus-property: 1`")
        self.assertEqual(sink, ["Ignored `bogus-property: 1`"])
        self.assertEqual(logger.level, level_before)

    def test_capture_does_not_propagate_to_ancestor_handlers(self):
        logger = logging.getLogger("weasyprint")
        propagate_before = logger.propagate
        sink = []
        with self.assertNoLogs(level=logging.WARNING):
            with _weasy_warning_capture.capture(sink):
                self.assertFalse(logger.propagate)
                logger.warning("Ignored `bogus-property: 1`")
        self.assertEqual(sink, ["Ignored `bogus-property: 1`"])
        self.assertIs(logger.propagate, propagate_before)

    def test_nested_capture_restores_state_once(self):
        logger = logging.getLogger("weasyprint")
        level_before = logger.level
        propagate_before = logger.propagate
        outer, inner = [], []
        with _weasy_warning_capture.capture(outer):
            with _weasy_warning_capture.capture(inner):
                logger.warning("inner")
            self.assertFalse(logger.propagate)
            self.assertEqual(logger.level, logging.WARNING)
            logger.warning("outer")
        self.assertEqual(logger.level, level_before)
        self.assertIs(logger.propagate, propagate_before)
        self.assertEqual(inner, ["inner"])
        self.assertEqual(outer, ["inner", "outer"])

    def test_render_error_includes_captured_warnings(self):
        engine = self.env["ir.actions.report"]._prepare_weasyprint_engine()
        engine._captured_warnings = ["Ignored `flex: 1` at 3:7"]
        error = engine._prepare_pdf_render_error("boom")
        self.assertIn("boom", str(error))
        self.assertIn("Ignored `flex: 1` at 3:7", str(error))
