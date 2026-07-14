"""Tests for the report-engine modernization batch.

Covers the per-record PDF metadata (title/author/creator/lang), the
``report_watermark`` context key, the ``dpi``/``jpeg_quality`` image knobs of
the PDF-options channel, and the scoped WeasyPrint warning capture.
"""

import logging

import odoo.tests

from odoo.addons.base.models.ir_actions_report import (
    PDF_OPTIONS_DATA_KEY,
    _watermark_css,
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
        """/Title is the evaluated print_report_name; author/creator/lang set."""
        import fitz  # PyMuPDF, an engine dependency

        with fitz.open(stream=self._render(), filetype="pdf") as doc:
            metadata = doc.metadata
            lang = doc.xref_get_key(doc.pdf_catalog(), "Lang")
        self.assertEqual(metadata["title"], "Sheet-Metadata Probe")
        self.assertEqual(metadata["author"], self.env.company.display_name)
        self.assertEqual(metadata["creator"], "Odoo")
        self.assertTrue(metadata["creationDate"])
        # Context lang en_US surfaces as the BCP 47 form in the PDF catalog.
        self.assertEqual(lang, ("string", "en-US"))

    def test_pdf_title_falls_back_to_report_label(self):
        """Without print_report_name the action label remains the title."""
        import fitz

        self.report.print_report_name = False
        with fitz.open(stream=self._render(), filetype="pdf") as doc:
            title = doc.metadata["title"]
        self.assertEqual(title, "Partner Sheet")

    def test_broken_print_report_name_never_blocks_printing(self):
        """A crashing expression falls back to the label instead of raising."""
        import fitz

        self.report.print_report_name = "object.missing_field_xyz"
        with fitz.open(stream=self._render(), filetype="pdf") as doc:
            title = doc.metadata["title"]
        self.assertEqual(title, "Partner Sheet")

    def test_watermark_context_stamps_every_copy(self):
        """report_watermark stamps the text; absent key leaves the page clean."""
        import fitz

        with fitz.open(stream=self._render(), filetype="pdf") as doc:
            self.assertNotIn("CONFIDENTIAL", doc[0].get_text())
        stamped = self._render(report_watermark="Confidential")
        with fitz.open(stream=stamped, filetype="pdf") as doc:
            # The overlay is styled text-transform: uppercase, and extraction
            # returns the transformed glyphs.
            self.assertIn("CONFIDENTIAL", doc[0].get_text())


@odoo.tests.tagged("post_install", "-at_install")
class TestWatermarkCss(odoo.tests.TransactionCase):
    def test_watermark_css_escapes_hostile_text(self):
        """Quotes/backslashes cannot break out of the CSS string."""
        css = _watermark_css('a"b\\c\nd')
        self.assertIn('content: "a\\"b\\\\c d";', css)

    def test_watermark_css_is_fixed_overlay(self):
        css = _watermark_css("DRAFT")
        self.assertIn("position: fixed;", css)
        self.assertIn('content: "DRAFT";', css)


@odoo.tests.tagged("post_install", "-at_install")
class TestPdfImageOptions(odoo.tests.TransactionCase):
    def test_build_pdf_options_image_knobs(self):
        Report = self.env["ir.actions.report"]
        self.assertIsNone(Report._build_pdf_options())
        options = Report._build_pdf_options(dpi=96, jpeg_quality=80)
        self.assertEqual(options, {"dpi": 96, "jpeg_quality": 80})

    def test_pdf_options_channel_forwards_image_knobs(self):
        """dpi/jpeg_quality ride the namespaced data channel into the render."""
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

    def test_render_error_includes_captured_warnings(self):
        engine = self.env["ir.actions.report"]._build_weasyprint_engine()
        engine._captured_warnings = ["Ignored `flex: 1` at 3:7"]
        error = engine._pdf_render_error("boom")
        self.assertIn("boom", str(error))
        self.assertIn("Ignored `flex: 1` at 3:7", str(error))
