import io
import logging
import threading
import time
from base64 import b64decode
from unittest.mock import patch

from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LAParams, LTFigure, LTTextBox
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from PIL import Image

import odoo.tests
from odoo import modules

_logger = logging.getLogger(__name__)


@odoo.tests.tagged("post_install", "-at_install", "post_install_l10n")
class TestReports(odoo.tests.TransactionCase):
    def test_get_report_rejects_bool_reference(self):
        """Reject bool refs like unknown strings.

        ``bool`` is an ``int`` subclass, so without a guard ``_get_report(False)``
        browsed an empty recordset and ``_get_report(True)`` crashed in
        ``browse()``. Both must raise ``ValueError``.
        """
        Report = self.env["ir.actions.report"]
        for ref in (False, True):
            with self.assertRaises(ValueError):
                Report._get_report(ref)

    def test_mixed_stylesheet_bodies_get_own_css(self):
        """Each body must render with its OWN stylesheets, not the first body's.

        Regression: in a mixed-language batch, bodies reference direction-specific
        bundles (rtl vs ltr). ``_preparse_external_css`` used to parse only the
        first body's ``<link>``s and apply them to every body, bleeding the first
        body's CSS onto the others.
        """
        engine = self.env["ir.actions.report"]._build_weasyprint_engine()
        ltr = (
            '<html><head><link rel="stylesheet" href="/a/ltr.css"/></head>'
            "<body>x</body></html>"
        )
        rtl = (
            '<html><head><link rel="stylesheet" href="/a/rtl.css"/></head>'
            "<body>y</body></html>"
        )
        # Stub the parsed-CSS map so routing is exercised without WeasyPrint.
        ltr_css, rtl_css = object(), object()
        parsed_by_url = {"/a/ltr.css": ltr_css, "/a/rtl.css": rtl_css}

        html0, css0 = engine._process_body_html(ltr, "", parsed_by_url)
        html1, css1 = engine._process_body_html(rtl, "", parsed_by_url)

        # Each body keeps only its own stylesheet, and its <link> is stripped.
        self.assertEqual(css0, [ltr_css])
        self.assertEqual(css1, [rtl_css])
        self.assertNotIn("stylesheet", html0)
        self.assertNotIn("stylesheet", html1)

        # A link with no parsed entry (parse failure) is left in place, not dropped.
        unknown = (
            '<html><head><link rel="stylesheet" href="/a/keep.css"/></head>'
            "<body>z</body></html>"
        )
        html2, css2 = engine._process_body_html(unknown, "", parsed_by_url)
        self.assertEqual(css2, [])
        self.assertIn("/a/keep.css", html2)

    def test_asset_css_parsed_once_per_process(self):
        """Content-addressed ``/web/assets`` stylesheets parse once per process.

        The parsed ``weasyprint.CSS`` lands in the ``_WeasySharedState`` cache
        keyed by the content-addressed URL, so a later render (fresh batch
        memo) reuses it without fetching or re-parsing. The mutable ``debug``
        unique must bypass the cache, and parsing must pass the shared
        ``font_config`` (without it WeasyPrint drops ``@font-face`` rules).
        """
        from odoo.addons.base.models import ir_actions_report as iar

        engine = self.env["ir.actions.report"]._build_weasyprint_engine()
        self.addCleanup(iar._weasy_state.reset_for_tests)

        body = (
            "<html><head>"
            '<link rel="stylesheet" '
            'href="/web/assets/abc123/web.report_assets_common.min.css"/>'
            "</head><body>x</body></html>"
        )
        debug_body = body.replace("/abc123/", "/debug/")
        sentinel = object()
        with patch.object(iar.weasyprint, "CSS", return_value=sentinel) as css_cls:
            _html0, css0 = engine._process_body_html(body, "", {}, fetcher=object())
            _html1, css1 = engine._process_body_html(body, "", {}, fetcher=object())
            self.assertEqual(css_cls.call_count, 1, "second render must hit the cache")
            self.assertEqual(css0, [sentinel])
            self.assertEqual(css1, [sentinel])
            self.assertIsNotNone(
                css_cls.call_args.kwargs.get("font_config"),
                "@font-face registration needs the shared font config at parse time",
            )
            engine._process_body_html(debug_body, "", {}, fetcher=object())
            engine._process_body_html(debug_body, "", {}, fetcher=object())
            self.assertEqual(css_cls.call_count, 3, "debug assets must not be cached")

    def test_render_entry_points_do_not_mutate_caller_data(self):
        """Render entry points must copy ``data`` before mutating it.

        ``data.setdefault("report_type", ...)`` used to inject a key into the
        caller's dict. The unknown ref raises after the defensive copy, so the
        caller's dict must be untouched.
        """
        Report = self.env["ir.actions.report"]
        data = {"foo": "bar"}
        with self.assertRaises(ValueError):
            Report._render_qweb_html("base.__no_such_report__", None, data=data)
        self.assertEqual(data, {"foo": "bar"}, "caller data dict must be unchanged")

    def test_tolerant_font_patch_serialized_under_concurrency(self):
        """Concurrent tolerant-font renders must not leak the fontTools patch.

        ``_write_pdf_tolerant_fonts`` monkey-patches a process-global fontTools
        method. Without serialization, a restore-order race lets the second
        render capture the first's patched function as its "original" and
        reinstall it permanently. Assert the patch window is mutually exclusive
        and the global is restored.
        """
        from fontTools.ttLib.tables.O_S_2f_2 import table_O_S_2f_2

        from odoo.addons.base.models import ir_actions_report as mod

        original = table_O_S_2f_2.setUnicodeRanges
        state = {"cur": 0, "max": 0}
        counter_lock = threading.Lock()

        class _FakeHTML:
            def __init__(self, **kwargs):
                pass

            def write_pdf(self, **kwargs):
                # Runs inside the patched critical section.
                with counter_lock:
                    state["cur"] += 1
                    state["max"] = max(state["max"], state["cur"])
                time.sleep(0.02)  # widen the window so any overlap is observed
                with counter_lock:
                    state["cur"] -= 1
                return b"%PDF-fake"

        with (
            patch.object(mod.weasyprint, "HTML", _FakeHTML),
            patch.object(mod, "FontConfiguration", lambda *a, **k: None),
            patch.object(mod, "CounterStyle", lambda *a, **k: None),
        ):
            threads = [
                threading.Thread(
                    target=mod._write_pdf_tolerant_fonts,
                    args=("<html/>", None, None),
                )
                for _ in range(5)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)

        self.assertEqual(
            state["max"],
            1,
            "tolerant-font patch window must be serialized (mutually exclusive)",
        )
        self.assertIs(
            table_O_S_2f_2.setUnicodeRanges,
            original,
            "the process-global fontTools patch must be fully restored",
        )

    def test_reports(self):
        invoice_domain = [
            (
                "move_type",
                "in",
                (
                    "out_invoice",
                    "out_refund",
                    "out_receipt",
                    "in_invoice",
                    "in_refund",
                    "in_receipt",
                ),
            )
        ]
        specific_model_domains = {
            "account.report_original_vendor_bill": [
                ("move_type", "in", ("in_invoice", "in_receipt"))
            ],
            "account.report_invoice_with_payments": invoice_domain,
            "account.report_invoice": invoice_domain,
            "l10n_th.report_commercial_invoice": invoice_domain,
        }
        extra_data_reports = {
            "im_livechat.report_livechat_conversation": {
                "company": self.env["res.company"].search([], limit=1)
            },
        }
        Report = self.env["ir.actions.report"]
        for report in Report.search([("report_type", "like", "qweb")]):
            report_model = "report.%s" % report.report_name
            try:
                self.env[report_model]
            except KeyError:
                # Only test the generic reports here
                _logger.info("testing report %s", report.report_name)
                report_model_domain = specific_model_domains.get(report.report_name, [])
                report_records = self.env[report.model].search(
                    report_model_domain, limit=10
                )
                if not report_records:
                    _logger.info(
                        "no record found skipping report %s", report.report_name
                    )

                data = extra_data_reports.get(report.report_name, {})
                # Test report generation
                if not report.multi:
                    for record in report_records:
                        Report._render_qweb_html(report.id, record.ids, data)
                else:
                    Report._render_qweb_html(report.id, report_records.ids, data)
            else:
                continue

    def test_report_reload_from_attachment(self):
        def get_attachments(res_id):
            return self.env["ir.attachment"].search(
                [("res_model", "=", "res.partner"), ("res_id", "=", res_id)]
            )

        Report = self.env["ir.actions.report"].with_context(force_report_rendering=True)

        report = Report.create(
            {
                "name": "test report",
                "report_name": "base.test_report",
                "model": "res.partner",
            }
        )

        self.env["ir.ui.view"].create(
            {
                "type": "qweb",
                "name": "base.test_report",
                "key": "base.test_report",
                "arch": """
                <main>
                    <div class="article" data-oe-model="res.partner" t-att-data-oe-id="docs.id">
                        <span t-field="docs.display_name" />
                    </div>
                </main>
            """,
            }
        )

        pdf_text = "0"

        def _render_html_to_pdf(*args, **kwargs):
            content = bytes(pdf_text, "utf-8")
            if kwargs.get("_split"):
                return [content] * len(args[1]) if len(args) > 1 else [content]
            return content

        self.patch(type(Report), "_render_html_to_pdf", _render_html_to_pdf)

        # sanity check: the report is not set to save attachment
        # assert that there are no pre-existing attachment
        partner_id = self.env.user.partner_id.id
        self.assertFalse(get_attachments(partner_id))
        pdf = report._render_qweb_pdf(report.id, [partner_id])
        self.assertFalse(get_attachments(partner_id))
        self.assertEqual(pdf[0], b"0")

        # set the report to reload from attachment and make one
        pdf_text = "1"
        report.attachment = "'test_attach'"
        report.attachment_use = True
        report._render_qweb_pdf(report.id, [partner_id])
        attach_1 = get_attachments(partner_id)
        self.assertTrue(attach_1.exists())

        # use the context key to not reload from attachment
        # and not create another one
        pdf_text = "2"
        report = report.with_context(report_pdf_no_attachment=True)
        pdf = report._render_qweb_pdf(report.id, [partner_id])
        attach_2 = get_attachments(partner_id)
        self.assertEqual(attach_2.id, attach_1.id)

        self.assertEqual(b64decode(attach_1.datas), b"1")
        self.assertEqual(pdf[0], b"2")

    def test_reload_from_attachment_null_mimetype(self):
        """A reused attachment with a NULL mimetype must not crash generation.

        ``mimetype`` is a nullable Char the ORM always populates, but a migration
        or raw SQL can leave it NULL. The image-conversion check in
        ``_render_qweb_pdf_prepare_streams`` must guard against that.
        """
        report = self.env["ir.actions.report"].create(
            {
                "name": "test report null mimetype",
                "report_name": "base.test_report",
                "model": "res.partner",
                "attachment": "'reused_attach'",
                "attachment_use": True,
            }
        )
        partner_id = self.env.user.partner_id.id
        attachment = self.env["ir.attachment"].create(
            {
                "name": "reused_attach",
                "res_model": "res.partner",
                "res_id": partner_id,
                "raw": b"%PDF-1.4 reused",
                "type": "binary",
            }
        )
        # Only a non-ORM write can leave mimetype NULL (the ORM re-guesses it).
        self.env.cr.execute(
            "UPDATE ir_attachment SET mimetype = NULL WHERE id = %s", (attachment.id,)
        )
        attachment.invalidate_recordset()
        self.assertFalse(attachment.mimetype)

        # Must not raise AttributeError('bool' object has no attribute 'startswith').
        streams = report._render_qweb_pdf_prepare_streams(
            report.id, {}, res_ids=[partner_id]
        )
        self.assertIn(partner_id, streams)
        self.assertTrue(streams[partner_id]["stream"])


# Some paper format examples
PAPER_SIZES = {
    (842, 1190): "A3",
    (595, 842): "A4",
    (420, 595): "A5",
    (297, 420): "A6",
    (612, 792): "Letter",
    (612, 1008): "Legal",
    (792, 1224): "Ledger",
}


class Box:
    """Position helper for PDF layout assertions."""

    def __init__(self, obj, page_height, page_width):
        self.x1 = round(obj.x0, 1)
        self.y1 = round(page_height - obj.y1, 1)
        self.x2 = round(obj.x1, 1)
        self.y2 = round(page_height - obj.y0, 1)
        self.page_height = page_height
        self.page_width = page_width

    @property
    def height(self):
        return self.y2 - self.y1

    @property
    def width(self):
        return self.x2 - self.x1

    @property
    def top(self):
        return self.y1

    @property
    def left(self):
        return self.x1

    @property
    def end_top(self):
        return self.y2

    @property
    def end_left(self):
        return self.x2

    @property
    def right(self):
        return self.page_width - self.x2

    @property
    def bottom(self):
        return self.page_height - self.y2

    def __lt__(self, other):
        return (self.y1, self.x1, self.y2, self.x2) < (
            other.y1,
            other.x1,
            other.y2,
            other.x2,
        )


class TestReportsRenderingCommon(odoo.tests.HttpCase):
    def setUp(self):
        super().setUp()
        self.report = self.env["ir.actions.report"].create(
            {
                "name": "Test Report Partner",
                "model": "res.partner",
                "report_name": "test_report.test_report_partner",
                "paperformat_id": self.env.ref("base.paperformat_euro").id,
            }
        )

        self.partners = self.env["res.partner"].create(
            [
                {
                    "name": f"Report record {i}",
                }
                for i in range(2)
            ]
        )

        self.report_view = self.env["ir.ui.view"].create(
            {
                "type": "qweb",
                "name": "test_report_partner",
                "key": "test_report.test_report_partner",
                "arch": "<t></t>",
            }
        )
        self.last_pdf_content = None
        self.last_pdf_content_saved = False

    def _addError(self, result, test, exc_info):
        if self.last_pdf_content and not self.last_pdf_content_saved:
            self.last_pdf_content_saved = True
            self.save_pdf()
        super()._addError(result, test, exc_info)

    def get_paper_format(self, mediabox):
        """Return ``(format, orientation)`` for a page mediabox.

        :param mediabox: a page mediabox, e.g. ``(0, 0, 595, 842)``
        :return: e.g. ``('A4', 'portait')``
        """
        x, y, width, height = mediabox
        self.assertEqual(
            (round(x), round(y)), (0, 0), "Expecting top corner to be 0, 0 "
        )
        orientation = "portait"
        # Round to integers — WeasyPrint produces exact mm→pt conversions
        # (e.g. 595.275591 for A4 width) while PAPER_SIZES uses integers.
        paper_size = (round(width), round(height))
        if width > height:
            orientation = "landscape"
            paper_size = (round(height), round(width))
        return PAPER_SIZES.get(paper_size, f"custom{paper_size}"), orientation

    def create_pdf(
        self,
        partners=None,
        header_content=None,
        page_content=None,
        footer_content=None,
    ):
        if header_content is None:
            header_content = """
                <img t-if="company.logo" t-att-src="image_data_uri(company.logo)" style="max-height: 45px;" alt="Logo"/>
                <span>Some header Text</span>
            """

        if footer_content is None:
            footer_content = """
                <div style="text-align:center">Footer for <t t-esc="o.name"/> Page: <span class="page"/> / <span class="topage"/></div>
            """

        if page_content is None:
            page_content = """
                <div class="page">
                    <div style="background-color:red">
                        Name: <t t-esc="o.name"/>
                    </div>
                </div>
            """

        self.report_view.arch = f"""
                <t t-name="test_report.test_report_partner">
                    <t t-set="company" t-value="res_company"/>
                    <t t-call="web.html_container">
                        <t t-foreach="docs" t-as="o">
                            <div class="header" style="font-family:Sans">
                                {header_content}
                            </div>
                            <div class="article" style="font-family:Sans">

                                {page_content}
                            </div>
                            <div class="footer" style="font-family:Sans">
                                {footer_content}
                            </div>
                        </t>
                    </t>
                </t>
            """
        # No web.external_layout: keeps header/footer editing simple; this tests
        # rendering only, not company base.document.layout.
        if partners is None:
            partners = self.partners
        self.last_pdf_content = (
            self.env["ir.actions.report"]
            .with_context(force_report_rendering=True)
            ._render_qweb_pdf(self.report, partners.ids)[0]
        )
        return self.last_pdf_content

    def save_pdf(self):
        assert self.last_pdf_content
        odoo.tests.save_test_file(
            self._testMethodName,
            self.last_pdf_content,
            "pdf_",
            "pdf",
            document_type="Report PDF",
            logger=_logger,
        )

    def _get_pdf_pages(self, pdf_content):
        ioBytes = io.BytesIO(pdf_content)
        parser = PDFParser(ioBytes)
        doc = PDFDocument(parser)
        return list(PDFPage.create_pages(doc))

    def _parse_pdf(self, pdf_content, expected_format=("A4", "portait")):
        """Return parsed elements per page.

        :param pdf_content: the PDF binary content
        :param expected_format: a get_paper_format-like format
        :return: list[list[(box, Element)]], one list of elements per page.
            ``box`` is a 4-float tuple from the top-left corner (to ease
            ordering), rounded to one digit.
        """
        pages = self._get_pdf_pages(pdf_content)
        ressource_manager = PDFResourceManager()
        device = PDFPageAggregator(ressource_manager, laparams=LAParams())
        interpreter = PDFPageInterpreter(ressource_manager, device)

        parsed_pages = []
        for page in pages:
            self.assertEqual(
                self.get_paper_format(page.mediabox),
                expected_format,
                "Expecting pdf to be in A4 portait format",
            )  # this is the default expected format and other layout assertions are based on this one.
            interpreter.process_page(page)
            layout = device.get_result()
            elements = []
            parsed_pages.append(elements)
            for obj in layout:
                box = Box(
                    obj,
                    page_height=pages[0].mediabox[3],
                    page_width=pages[0].mediabox[2],
                )
                if isinstance(obj, LTTextBox):
                    # inverse x to start from top left corner
                    elements.append((box, obj.get_text().strip()))
                elif isinstance(obj, LTFigure):
                    elements.append((box, "LTFigure"))
            elements.sort()

        return parsed_pages

    def assertPageFormat(self, paper_format, orientation):
        pdf_content = self.create_pdf()
        pages = self._get_pdf_pages(pdf_content)
        self.assertEqual(len(pages), 2)
        for page in pages:
            self.assertEqual(
                self.get_paper_format(page.mediabox),
                (paper_format, orientation),
                f"Expecting pdf to be in {paper_format} {orientation} format",
            )


@odoo.tests.tagged("post_install", "-at_install", "pdf_rendering")
class TestReportsRendering(TestReportsRenderingCommon):
    """Exercise PDF rendering, especially multipage headers/footers via CSS
    running elements.

    A custom template without web.external_layout is used on purpose to test
    rendering only, without any company document.layout logic.
    """

    def test_format_A4(self):
        self.report.paperformat_id = self.env.ref("base.paperformat_euro")
        self.assertPageFormat("A4", "portait")

    def test_format_letter(self):
        self.report.paperformat_id = self.env.ref("base.paperformat_us")
        self.assertPageFormat("Letter", "portait")

    def test_format_landscape(self):
        paper_format = self.env.ref("base.paperformat_euro")
        paper_format.orientation = "Landscape"
        self.report.paperformat_id = paper_format
        self.assertPageFormat("A4", "landscape")

    def test_layout(self):
        pdf_content = self.create_pdf()
        pages = self._parse_pdf(pdf_content)
        self.assertEqual(len(pages), 2)

        page_contents = [[elem[1] for elem in page] for page in pages]

        expected_pages_content = [
            [
                "LTFigure",
                "Some header Text",
                f"Name: {partner.name}",
                f"Footer for {partner.name} Page: 1 / 1",
            ]
            for partner in self.partners
        ]

        self.assertEqual(
            page_contents,
            expected_pages_content,
        )

        page_positions = [[elem[0] for elem in page] for page in pages]
        logo, header, content, footer = page_positions[0]

        # leaving this as reference but this is too fragile to make a strict assertion
        # 14.3, 29.6, 43.1, 137.2     # logo
        # 19.1, 137.2, 32.5, 214.2   # header
        # 111.3, 29.6, 124.8, 123.7   # content
        # 751.6, 220.1, 765.1, 375.0  # footer

        #
        #   \ \ / // _ \ | | | || _ \  | |
        #    \ V /| (_) || |_| ||   /  | |__ / _ \/ _` |/ _ \     Some header Text
        #     |_|  \___/  \___/ |_|_\  |____|\___/\__, |\___/
        #
        #
        #   Name: Report record 0
        #
        #
        #
        #
        #
        #
        #             Footer for Report record 0 Page: 1 / 1
        #
        #

        self.assertEqual(
            logo.left,
            content.left,
            "Logo and content should have the same left margin",
        )
        # WeasyPrint renders inline whitespace (between <img> and <span>) as a
        # visible gap (~3pt), whereas wkhtmltopdf absorbed it into the text box.
        self.assertAlmostEqual(
            header.left, logo.end_left, delta=5, msg="Header starts after logo"
        )
        self.assertGreaterEqual(
            header.top, logo.top, "header is vertically centered on logo"
        )
        self.assertGreaterEqual(
            logo.end_top,
            header.end_top,
            "header is vertically centered on logo",
        )
        self.assertGreaterEqual(content.top, logo.end_top, "Content is bellow logo")
        self.assertGreaterEqual(footer.top, content.end_top, "Footer is bellow content")
        self.assertGreaterEqual(
            100, footer.bottom, "Footer is on the bottom of the page"
        )
        self.assertAlmostEqual(
            footer.left, footer.right, -1, "Footer is centered on the page"
        )

    def test_engine_split_and_bounded_merge_paths(self):
        """Drive the split and large-batch memory-bounded paths directly.

        ``split`` returns one PDF per body; a non-split batch above
        ``report.weasyprint_native_merge_max`` merges incrementally with pypdf.
        Both are exercised on plain inline HTML, independent of the report
        pipeline.
        """
        report_model = self.env["ir.actions.report"]
        engine = report_model._build_weasyprint_engine()
        bodies = [
            f"<html><head></head><body><div>Doc {i}</div></body></html>"
            for i in range(3)
        ]
        page_css = "@page { size: A4; margin: 10mm; }"

        # split=True -> list of single-page PDFs, Documents freed between bodies.
        pdfs = engine.render(bodies, page_css, split=True)
        self.assertEqual(len(pdfs), 3)
        for pdf in pdfs:
            self.assertTrue(pdf.startswith(b"%PDF"))
            self.assertEqual(len(self._get_pdf_pages(pdf)), 1)

        # Threshold 1 (< 3 bodies) forces the incremental pypdf merge path.
        # The threshold is frozen at construction, so rebuild the engine after
        # changing the config parameter.
        self.env["ir.config_parameter"].sudo().set_param(
            "report.weasyprint_native_merge_max", "1"
        )
        engine = report_model._build_weasyprint_engine()
        merged = engine.render(bodies, page_css, split=False)
        self.assertTrue(merged.startswith(b"%PDF"))
        self.assertEqual(len(self._get_pdf_pages(merged)), 3)

    def test_batch_bounded_merge_matches_native(self):
        """The large-batch pypdf merge must equal WeasyPrint's native merge.

        Rendering the same records with the native ``Document.copy()`` merge and
        with the memory-bounded incremental merge must yield the same pages: the
        optimisation changes cost, not output.
        """
        partners = self.env["res.partner"].create(
            [{"name": f"Batch record {i}"} for i in range(3)]
        )
        icp = self.env["ir.config_parameter"].sudo()

        icp.set_param("report.weasyprint_native_merge_max", "100")
        native_pages = [
            [elem[1] for elem in page]
            for page in self._parse_pdf(self.create_pdf(partners=partners))
        ]

        icp.set_param("report.weasyprint_native_merge_max", "1")
        bounded_pages = [
            [elem[1] for elem in page]
            for page in self._parse_pdf(self.create_pdf(partners=partners))
        ]

        self.assertEqual(len(native_pages), 3)
        self.assertEqual(bounded_pages, native_pages)

    def test_report_pdf_page_break(self):

        partners = self.partners[:2]
        page_content = """
                <div class="page">
                    <div style="background-color:red">
                        Name: <t t-esc="o.name"/>
                    </div>
                    <div style="page-break-before:always;background-color:blue">
                        Last page for <t t-esc="o.name"/>
                    </div>
                </div>
            """

        pdf_content = self.create_pdf(partners=partners, page_content=page_content)

        pages = self._parse_pdf(pdf_content)

        self.assertEqual(len(pages), 4, "Expecting 2 pages * 2 partners")

        expected_pages_contents = []
        for partner in self.partners:
            expected_pages_contents.extend(
                [
                    [
                        "LTFigure",  # logo
                        "Some header Text",
                        f"Name: {partner.name}",
                        f"Footer for {partner.name} Page: 1 / 2",
                    ],
                    [
                        "LTFigure",  # logo
                        "Some header Text",
                        f"Last page for {partner.name}",
                        f"Footer for {partner.name} Page: 2 / 2",
                    ],
                ]
            )
        pages_contents = [[elem[1] for elem in page] for page in pages]
        self.assertEqual(pages_contents, expected_pages_contents)

    def test_pdf_render_page_overflow(self):
        nb_lines = 80

        page_content = f"""
            <div class="page">
                <div style="background-color:red">
                    Name: <t t-esc="o.name"/>
                    <div t-foreach="range({nb_lines})" t-as="pos" t-esc="pos"/>
                </div>
            </div>
        """
        pdf_content = self.create_pdf(page_content=page_content)
        pages = self._parse_pdf(pdf_content)

        self.assertEqual(
            len(pages),
            6,
            "6 pages are expected, 3 per record (you may ensure `nb_lines` has a correct value to generate an oveflow)",
        )
        first_page_break_at = int(
            pages[1][2][1].split("\n")[0]
        )  # This element should be the first line, 61 when this test was written
        second_page_break_at = int(pages[2][2][1].split("\n")[0])

        # There is some inconsistency caused by the pdfminer library when \n are placed, to be sure we don't have issues
        # We put one element per line
        pages_contents = []
        for page in pages:
            page_content = []
            for elem in page:
                if "\n" in elem[1]:
                    page_content.extend(elem[1].split("\n"))
                else:
                    page_content.append(elem[1])
            pages_contents.append(page_content)

        expected_pages_contents = []
        # These changes are needed to format the page content and the expected page the same due to the inconsistency
        # With the pdfminer library
        for partner in self.partners:

            def create_page_content(
                start, end, page_number, include_name=False, partner=partner
            ):
                content = [
                    "LTFigure",  # logo
                    "Some header Text",
                ]
                if include_name:
                    content.append(f"Name: {partner.name}")
                content.extend([str(i) for i in range(start, end)])
                content.append(f"Footer for {partner.name} Page: {page_number} / 3")
                return content

            expected_pages_contents.extend(
                [
                    create_page_content(0, first_page_break_at, 1, include_name=True),
                    create_page_content(first_page_break_at, second_page_break_at, 2),
                    create_page_content(second_page_break_at, nb_lines, 3),
                ]
            )

        self.assertEqual(pages_contents, expected_pages_contents)

    def test_thead_tbody_repeat(self):
        """
        Check that thead and t-foot are repeated after page break inside a tbody
        """
        nb_lines = 50
        page_content = f"""
            <div class="page">
                <table class="table">
                    <thead><tr><th> T1 </th><th> T2 </th><th> T3 </th></tr></thead>
                    <tbody>
                    <t t-foreach="range({nb_lines})" t-as="pos">
                        <tr><td><t t-esc="pos"/></td><td><t t-esc="pos"/></td><td><t t-esc="pos"/></td></tr>
                    </t>
                    </tbody>
                    <tfoot><tr><th> T1 </th><th> T2 </th><th> T3 </th></tr></tfoot>
                </table>
            </div>
        """

        pdf_content = self.create_pdf(page_content=page_content)
        pages = self._parse_pdf(pdf_content)

        self.assertEqual(
            len(pages),
            6,
            "6 pages are expected, 3 per record (you may ensure `nb_lines` has a correct value to generate an oveflow)",
        )

        # This element should be the first line of the table, 28 when this test was written
        first_page_break_at = int(pages[1][5][1])
        second_page_break_at = int(pages[2][5][1])

        def expected_table(start, end):
            table = ["T1", "T2", "T3"]  # thead
            for i in range(start, end):
                table += [str(i), str(i), str(i)]
            table += ["T1", "T2", "T3"]  # tfoot
            return table

        expected_pages_contents = []
        for partner in self.partners:
            expected_pages_contents.extend(
                [
                    [
                        "LTFigure",  # logo
                        "Some header Text",
                        *expected_table(0, first_page_break_at),
                        f"Footer for {partner.name} Page: 1 / 3",
                    ],
                    [
                        "LTFigure",  # logo
                        "Some header Text",
                        *expected_table(first_page_break_at, second_page_break_at),
                        f"Footer for {partner.name} Page: 2 / 3",
                    ],
                    [
                        "LTFigure",  # logo
                        "Some header Text",
                        *expected_table(second_page_break_at, nb_lines),
                        f"Footer for {partner.name} Page: 3 / 3",
                    ],
                ]
            )

        pages_contents = [[elem[1] for elem in page] for page in pages]
        self.assertEqual(pages_contents, expected_pages_contents)

    def test_report_specific_paperformat_args(self):
        """`specific_paperformat_args` must override the paperformat in @page CSS."""
        css = self.env["ir.actions.report"]._paperformat_to_css(
            self.env["report.paperformat"].new(
                {
                    "format": "A4",
                    "margin_top": 25,
                    "margin_left": 50,
                    "margin_bottom": 75,
                    "margin_right": 100,
                    "orientation": "portrait",
                    "header_line": True,
                }
            ),
            landscape=False,
            specific_paperformat_args={
                "data-report-margin-top": 0,
                "data-report-margin-bottom": 0,
            },
        )
        self.assertIn("size: a4 portrait", css)
        self.assertIn("margin: 0.0mm 100.0mm 0.0mm 50.0mm", css)
        self.assertIn("border-bottom: 1px solid black", css)
        self.assertIn("content: element(page-header)", css)
        self.assertIn("content: element(page-footer)", css)
        # Running elements and page counters are now declared statically
        # in report_paged_media.css, not emitted per-report by _paperformat_to_css().
        self.assertNotIn("counter(page)", css)
        self.assertNotIn("counter(pages)", css)
        self.assertNotIn("running(page-header)", css)
        self.assertNotIn("running(page-footer)", css)

    def test_paperformat_to_css_landscape_from_html_attribute(self):
        """data-report-landscape in specific_paperformat_args must force landscape.

        Regression: _paperformat_to_css read specific_paperformat_args for margins
        but not for the landscape attribute, so ``data_report_landscape=True``
        produced portrait PDFs.
        """
        Report = self.env["ir.actions.report"]
        pf = self.env["report.paperformat"].new(
            {
                "format": "A4",
                "orientation": "Portrait",
                "margin_top": 10,
                "margin_left": 10,
                "margin_bottom": 10,
                "margin_right": 10,
            }
        )
        # Truthy string values must override the portrait paperformat
        for truthy in ("True", "1"):
            with self.subTest(value=truthy):
                css = Report._paperformat_to_css(
                    pf,
                    landscape=False,
                    specific_paperformat_args={"data-report-landscape": truthy},
                )
                self.assertIn(
                    "size: a4 landscape",
                    css,
                    f"Expected landscape orientation for data-report-landscape={truthy!r}",
                )
        # Falsy string values must NOT override portrait
        for falsy in ("False", "0", "false", ""):
            with self.subTest(value=falsy):
                css = Report._paperformat_to_css(
                    pf,
                    landscape=False,
                    specific_paperformat_args={"data-report-landscape": falsy},
                )
                self.assertIn(
                    "size: a4 portrait",
                    css,
                    f"Expected portrait orientation for data-report-landscape={falsy!r}",
                )

    def test_format_landscape_from_template_attribute(self):
        """QWeb data_report_landscape=True forces a landscape PDF even when the
        paperformat record is Portrait.

        End-to-end: ``data_report_landscape`` renders as
        ``data-report-landscape="True"`` on the HTML root, which
        ``_prepare_weasyprint_html`` captures into ``specific_paperformat_args``
        for ``_paperformat_to_css`` to honour. Two partners also exercise the
        multi-record path.
        """
        paper_format = self.env.ref("base.paperformat_euro")
        paper_format.orientation = "Portrait"
        self.report.paperformat_id = paper_format

        self.report_view.arch = """
            <t t-name="test_report.test_report_partner">
                <t t-set="data_report_landscape" t-value="True"/>
                <t t-set="company" t-value="res_company"/>
                <t t-call="web.html_container">
                    <t t-foreach="docs" t-as="o">
                        <div class="article" style="font-family:Sans">
                            <div class="page">Name: <t t-esc="o.name"/></div>
                        </div>
                    </t>
                </t>
            </t>
        """
        pdf_content = (
            self.env["ir.actions.report"]
            .with_context(force_report_rendering=True)
            ._render_qweb_pdf(self.report, self.partners.ids)[0]
        )
        pages = self._get_pdf_pages(pdf_content)
        self.assertTrue(pages, "Expected at least one rendered page")
        for page in pages:
            paper, orient = self.get_paper_format(page.mediabox)
            self.assertEqual(paper, "A4")
            self.assertEqual(
                orient,
                "landscape",
                "Expected landscape orientation from data_report_landscape template variable",
            )

    def test_paperformat_to_css_bad_margin(self):
        """A malformed data-report-margin-* falls back to the paperformat value
        instead of raising ValueError (IAR-L4).

        Templates supply these as strings; a value like "2cm" must not crash the
        render with an uncaught HTTP 500.
        """
        Report = self.env["ir.actions.report"]
        pf = self.env["report.paperformat"].new(
            {
                "format": "A4",
                "margin_top": 25,
                "margin_left": 50,
                "margin_bottom": 75,
                "margin_right": 100,
                "orientation": "portrait",
            }
        )
        css = Report._paperformat_to_css(
            pf,
            landscape=False,
            specific_paperformat_args={
                "data-report-margin-top": "2cm",  # malformed: unit suffix
                "data-report-margin-bottom": "not-a-number",
            },
        )
        # Falls back to paperformat margins (25 top, 75 bottom); no exception.
        self.assertIn("margin: 25.0mm 100.0mm 75.0mm 50.0mm", css)

    def test_render_html_to_image_format(self):
        """_render_html_to_image rasterizes real HTML and honours size + format.

        Exercises the real WeasyPrint -> PyMuPDF -> PIL path (no stub). The
        method early-returns ``[None] * len(bodies)`` under ``current_test``, so
        we clear that guard to cover the real rasterize/resize/format logic
        (IAR-T1). WeasyPrint 68 has no ``write_png``, so a stubbed backend would
        hide a fully broken method.
        """
        Report = self.env["ir.actions.report"]

        # Bypass the current_test early-return so the real backend runs.
        self.patch(modules.module, "current_test", False)

        # JPEG (default) — RGB, exact target size.
        jpg_images = Report._render_html_to_image(
            ["<p>x</p>"], width=20, height=10, image_format="jpg"
        )
        self.assertEqual(len(jpg_images), 1)
        self.assertIsNotNone(jpg_images[0], "image rendering returned None")
        with Image.open(io.BytesIO(jpg_images[0])) as out:
            self.assertEqual(out.size, (20, 10))
            self.assertEqual(out.format, "JPEG")

        # PNG — preserves format and target size.
        png_images = Report._render_html_to_image(
            ["<p>x</p>"], width=8, height=16, image_format="png"
        )
        self.assertIsNotNone(png_images[0], "image rendering returned None")
        with Image.open(io.BytesIO(png_images[0])) as out:
            self.assertEqual(out.size, (8, 16))
            self.assertEqual(out.format, "PNG")


@odoo.tests.tagged("post_install", "-at_install", "-standard", "pdf_rendering")
class TestReportsRenderingLimitations(TestReportsRenderingCommon):
    def test_no_clip(self):
        """Demonstrate the limitation: a fixed margin is added on top of the document."""
        header_content = """
            <div style="background-color:blue">
                <div t-foreach="range(15)" t-as="pos" t-esc="'Header %s' % pos"/>
            </div>
        """
        page_content = """
            <div class="page">
                <div style="background-color:red; margin-left:100px">
                    <div t-foreach="range(10)" t-as="pos" t-esc="'Content %s' % pos"/>
                </div>
            </div>
        """
        # page margin keeps header and body from being read as the same box
        pdf_content = self.create_pdf(
            page_content=page_content, header_content=header_content
        )
        pages = self._parse_pdf(pdf_content)
        self.assertEqual(len(pages), 2, "2 partners")
        page = pages[0]
        self.assertEqual(len(page), 3, "Expecting 3 box per page, Header, body, footer")
        header = page[0][0]
        content = page[1][0]
        self.assertGreaterEqual(
            content.top,
            header.end_top,
            "EXISTING LIMITATION: large header shouldn't overflow on body, but they do",
        )


@odoo.tests.tagged("post_install", "-at_install")
class TestAggregatePdfReports(odoo.tests.HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partners = cls.env["res.partner"].create(
            [
                {"name": "Rodion Romanovich Raskolnikov"},
                {"name": "Dmitri Prokofich Razumikhin"},
                {"name": "Porfiry Petrovich"},
            ]
        )

        cls.env["ir.actions.report"].create(
            {
                "name": "test report",
                "report_name": "base.test_report",
                "model": "res.partner",
            }
        )

    def test_aggregate_report_with_some_resources_reloaded_from_attachment(
        self,
    ):
        """Regression opw-3827700: a multi-record report failed when a middle
        record had an attachment and 'Reload from attachment' was enabled (an
        indexing bug).
        """
        self.env["ir.ui.view"].create(
            {
                "type": "qweb",
                "name": "base.test_report",
                "key": "base.test_report",
                "arch": """
                    <main>
                        <div t-foreach="docs" t-as="user">
                            <div class="article" data-oe-model="res.partner" t-att-data-oe-id="user.id">
                                <span t-esc="user.display_name"/>
                            </div>
                        </div>
                    </main>
                    """,
            }
        )
        self.assert_report_creation("base.test_report", self.partners, self.partners[1])

    def test_aggregate_report_with_some_resources_reloaded_from_attachment_with_multiple_page_report(
        self,
    ):
        """Same as the single-page variant, but for reports spanning multiple
        pages per record.
        """
        self.env["ir.ui.view"].create(
            {
                "type": "qweb",
                "name": "base.test_report",
                "key": "base.test_report",
                "arch": """
                    <main>
                        <div t-foreach="docs" t-as="user">
                            <div class="article" data-oe-model="res.partner" t-att-data-oe-id="user.id" >
                                <!-- This headline helps report generation to split pdfs per record after it generates
                                     the report in bulk by creating an outline. -->
                                <h1>Name</h1>
                                <!-- Make this a multipage report. -->
                                <div t-foreach="range(100)" t-as="i">
                                    <span t-esc="i"/> - <span t-esc="user.display_name"/>
                                </div>
                            </div>
                        </div>
                    </main>
                    """,
            }
        )
        self.assert_report_creation("base.test_report", self.partners, self.partners[1])

    def assert_report_creation(self, report_ref, records, record_to_report):
        self.assertIn(
            record_to_report,
            records,
            "Record to report must be in records list",
        )

        reports = self.env["ir.actions.report"].with_context(
            force_report_rendering=True
        )

        # Make sure attachments are created.
        report = reports._get_report(report_ref)
        if not report.attachment:
            report.attachment = "object.name + '.pdf'"
        report.attachment_use = True

        # Generate report for chosen record to create an attachment.
        record_report, content_type = reports._render_qweb_pdf(
            report_ref, res_ids=record_to_report.id
        )
        self.assertEqual(content_type, "pdf", "Report is not a PDF")
        self.assertTrue(record_report, "PDF not generated")

        # Make sure the attachment is created.
        report = reports._get_report(report_ref)
        self.assertTrue(
            report.retrieve_attachment(record_to_report),
            "Attachment not generated",
        )

        aggregate_report_content, content_type = reports._render_qweb_pdf(
            report_ref, res_ids=records.ids
        )
        self.assertEqual(content_type, "pdf", "Report is not a PDF")
        self.assertTrue(aggregate_report_content, "PDF not generated")
        for record in records:
            self.assertTrue(
                report.retrieve_attachment(record), "Attachment not generated"
            )
