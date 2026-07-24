"""Tests for the pptx / xlsx / opendoc content extractors."""

import io
import zipfile

from odoo.tests import TransactionCase, tagged

OFFICE_NS = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
TEXT_NS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
TABLE_NS = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"


def _make_pptx(texts):
    body = "".join(f"<a:t>{t}</a:t>" for t in texts)
    slide = (
        '<?xml version="1.0"?>'
        '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
        ' xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        f"{body}</p:sld>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("ppt/slides/slide1.xml", slide)
    return buffer.getvalue()


def _make_opendoc(mimetype, inner_body):
    content = (
        '<?xml version="1.0"?>'
        f'<office:document-content xmlns:office="{OFFICE_NS}"'
        f' xmlns:text="{TEXT_NS}" xmlns:table="{TABLE_NS}">'
        f"<office:body>{inner_body}</office:body></office:document-content>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("mimetype", mimetype)
        zf.writestr("content.xml", content)
    return buffer.getvalue()


@tagged("post_install", "-at_install")
class TestIndexExtraFormats(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Attachment = cls.env["ir.attachment"]

    def test_index_pptx_extracts_slide_text(self):
        """A .pptx payload yields its slide text runs."""
        result = self.Attachment._index_pptx(_make_pptx(["Slide title", "Bullet"]))
        self.assertIn("Slide title", result)
        self.assertIn("Bullet", result)

    def test_index_pptx_non_zip_is_empty(self):
        """Non-zip bytes produce no pptx index (boundary)."""
        self.assertEqual(self.Attachment._index_pptx(b"not a zip"), "")

    def test_index_xlsx_extracts_cells(self):
        """A .xlsx payload yields its sheet name and cell values."""
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest("openpyxl not installed")
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Data"
        sheet.append(["Name", "Amount"])
        sheet.append(["Alice", 10])
        buffer = io.BytesIO()
        workbook.save(buffer)
        result = self.Attachment._index_xlsx(buffer.getvalue())
        self.assertIn("Alice", result)
        self.assertIn("Data", result)

    def test_index_odt_extracts_paragraphs(self):
        """An .odt payload yields its paragraph text."""
        body = f'<text:p xmlns:text="{TEXT_NS}">First para</text:p>'
        data = _make_opendoc("application/vnd.oasis.opendocument.text", body)
        result = self.Attachment._index_opendoc(data)
        self.assertIn("First para", result)

    def test_index_ods_extracts_cells(self):
        """An .ods payload yields its table cells as CSV rows."""
        rows = ""
        for cells in (["Header"], ["Value1"]):
            tcs = "".join(
                f"<table:table-cell><text:p>{c}</text:p></table:table-cell>"
                for c in cells
            )
            rows += f"<table:table-row>{tcs}</table:table-row>"
        table = f'<table:table table:name="Sheet1">{rows}</table:table>'
        data = _make_opendoc("application/vnd.oasis.opendocument.spreadsheet", table)
        result = self.Attachment._index_opendoc(data)
        self.assertIn("Value1", result)
