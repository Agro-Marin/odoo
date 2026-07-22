"""Tests for the attachment content-indexing extractors."""

import io
import zipfile

from odoo.tests import TransactionCase, tagged

from odoo.addons.attachment_indexation.models.ir_attachment import _csv_escape

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _make_docx(paragraphs):
    """Build a minimal .docx (zip with word/document.xml) in memory."""
    body = "".join(f"<w:p><w:t>{p}</w:t></w:p>" for p in paragraphs)
    document = (
        '<?xml version="1.0"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body>' + body + "</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("word/document.xml", document)
    return buffer.getvalue()


@tagged("post_install", "-at_install")
class TestIndexContent(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Attachment = cls.env["ir.attachment"]

    def test_csv_escape_quotes_special_chars(self):
        """Values with commas/quotes/newlines get quoted and escaped."""
        self.assertEqual(_csv_escape("plain"), "plain")
        self.assertEqual(_csv_escape("a,b"), '"a,b"')
        self.assertEqual(_csv_escape('say "hi"'), '"say ""hi"""')
        self.assertEqual(_csv_escape(None), "")

    def test_index_docx_extracts_paragraph_text(self):
        """A .docx payload yields its paragraph text."""
        data = _make_docx(["Hello world", "Second line"])
        buf = self.Attachment._index_docx(data)
        self.assertIn("Hello world", buf)
        self.assertIn("Second line", buf)

    def test_index_docx_non_zip_is_empty(self):
        """Non-zip bytes produce no docx index (boundary)."""
        self.assertEqual(self.Attachment._index_docx(b"not a zip file"), "")

    def test_index_dispatch_prefers_docx_extractor(self):
        """_index routes a docx payload through the docx extractor."""
        data = _make_docx(["Indexed body"])
        result = self.Attachment._index(data, DOCX_MIME)
        self.assertIn("Indexed body", result)

    def test_index_read_size_full_for_office_docs(self):
        """Office/pdf mimetypes read the whole file (None cap)."""
        self.assertIsNone(self.Attachment._index_read_size(DOCX_MIME))

    def test_index_read_size_bounded_for_plain_text(self):
        """Plain text defers to the base bounded prefix (not None)."""
        self.assertIsNotNone(self.Attachment._index_read_size("text/plain"))
