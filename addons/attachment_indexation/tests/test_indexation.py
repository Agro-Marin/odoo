import io
import zipfile
from pathlib import Path
from unittest import skipIf
from unittest.mock import patch

from werkzeug.datastructures import FileStorage

from odoo.tests.common import TransactionCase, tagged
from odoo.tools.misc import file_open

directory = Path(__file__).parent


def _build_docx(document_xml):
    """Build minimal .docx-shaped zip bytes with a single word/document.xml entry."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", document_xml)
    return buf.getvalue()


try:
    from pdfminer.pdfinterp import PDFResourceManager
except ImportError:
    PDFResourceManager = None


@tagged("post_install", "-at_install")
class TestCaseIndexation(TransactionCase):
    @skipIf(PDFResourceManager is None, "pdfminer not installed")
    def test_attachment_pdf_indexation(self):
        with file_open(str(directory / "files" / "test_content.pdf"), "rb") as file:
            pdf = file.read()
            text = self.env["ir.attachment"]._index(pdf, "application/pdf")
            self.assertEqual(
                text, "TestContent!!", "the index content should be correct"
            )

    def test_docx_indexation_happy_path(self):
        """A well-formed .docx parses normally and its text is extracted."""
        document_xml = (
            b'<?xml version="1.0"?>'
            b'<w:document xmlns:w="ns"><w:body><w:p>Hello</w:p></w:body></w:document>'
        )
        text = self.env["ir.attachment"]._index_docx(_build_docx(document_xml))
        self.assertIn("Hello", text)

    def test_docx_indexation_rejects_entity_declarations(self):
        """A .docx whose document.xml declares an XML entity must not be
        parsed with entity substitution: defusedxml must reject it outright
        (caught by the broad except, buf stays empty), instead of silently
        expanding it like the plain xml.dom.minidom parser used to."""
        document_xml = (
            b'<?xml version="1.0"?>'
            b'<!DOCTYPE w:document [<!ENTITY xxe "boom">]>'
            b'<w:document xmlns:w="ns"><w:body><w:p>&xxe;</w:p></w:body></w:document>'
        )
        text = self.env["ir.attachment"]._index_docx(_build_docx(document_xml))
        self.assertEqual(
            text, "", "entity declarations must not be substituted into the index"
        )

    def test_docx_indexation_skips_oversized_entry(self):
        """A word/document.xml entry larger than _INDEX_MAX_BYTES must be
        skipped before parsing, not read/parsed in full (zip-bomb guard)."""
        Att = self.env["ir.attachment"]
        padding = b"<!-- " + b"a" * (Att._INDEX_MAX_BYTES + 1) + b" -->"
        document_xml = (
            b'<?xml version="1.0"?>'
            b'<w:document xmlns:w="ns">'
            + padding
            + b"<w:body><w:p>Hello</w:p></w:body></w:document>"
        )
        text = Att._index_docx(_build_docx(document_xml))
        self.assertEqual(text, "", "an oversized entry must be skipped, not parsed")

    def test_index_read_size_documents_read_full(self):
        """Parsed document mimetypes request a full read-back from the streaming
        create path, text keeps its bounded prefix, and unindexable media skips
        the read so it streams flat."""
        Att = self.env["ir.attachment"]
        self.assertIsNone(Att._get_index_read_size("application/pdf"))
        self.assertIsNone(
            Att._get_index_read_size(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        )
        self.assertEqual(Att._get_index_read_size("text/plain"), Att._INDEX_MAX_BYTES)
        self.assertEqual(Att._get_index_read_size("video/mp4"), 0)
        self.assertEqual(Att._get_index_read_size("image/png"), 0)

    def test_index_read_size_generic_mimetype_reads_full(self):
        """An unlabelled or generic mimetype (empty, or the browser's
        'application/octet-stream' fallback) must still read the whole file
        rather than skip: this method only sees the caller's declared
        string, so only `_index`'s Document, once given the full bytes, can
        recognise a real document the declared string could not. Genuinely
        unindexable media is always declared with its own specific
        mimetype, never a generic one, so it still skips (asserted above)."""
        Att = self.env["ir.attachment"]
        self.assertIsNone(Att._get_index_read_size(""))
        self.assertIsNone(Att._get_index_read_size("application/octet-stream"))

    @skipIf(PDFResourceManager is None, "pdfminer not installed")
    def test_streamed_pdf_reads_full_content_and_indexes(self):
        """A PDF uploaded over the streaming path is read back in full and indexed."""
        # A capped read would parse a large PDF from a truncated prefix and lose its index.
        Att = self.env["ir.attachment"]
        with file_open(str(directory / "files" / "test_content.pdf"), "rb") as f:
            pdf = f.read()

        read_sizes = []
        model_cls = type(Att)
        real_read = model_cls._read_file

        def read_spy(model, fname, size=None):
            read_sizes.append(size)
            return real_read(model, fname, size=size)

        with patch.object(model_cls, "_read_file", read_spy):
            fs = FileStorage(
                stream=io.BytesIO(pdf), filename="c.pdf", content_type="application/pdf"
            )
            att = Att._create_from_request_file(fs, mimetype="TRUST")

        self.assertTrue(att.store_fname, "PDF must stream to the filestore")
        self.assertEqual(att.index_content, "TestContent!!")
        # the index read-back asked for the WHOLE file (size=None), never the
        # bounded prefix the pre-seam code used.
        self.assertIn(None, read_sizes, "streamed PDF index read must be unbounded")
        self.assertNotIn(
            Att._INDEX_MAX_BYTES,
            read_sizes,
            "must not cap the document index read at the prefix",
        )

    def test_streamed_generic_mimetype_still_indexes_a_real_docx(self):
        """`mimetype='TRUST'` hands `_create_from_request_file` the caller's
        declared Content-Type verbatim, with no filename- or byte-based
        correction (this is `documents.py`'s upload path for internal
        users). When that declared type is generic
        (`application/octet-stream`), the real document underneath must
        still be read back in full and indexed, not silently skipped."""
        Att = self.env["ir.attachment"]
        document_xml = (
            b'<?xml version="1.0"?>'
            b'<w:document xmlns:w="ns"><w:body><w:p>PROBE_TEXT_HERE</w:p>'
            b"</w:body></w:document>"
        )
        fs = FileStorage(
            stream=io.BytesIO(_build_docx(document_xml)),
            filename="report.docx",
            content_type="application/octet-stream",
        )
        att = Att._create_from_request_file(fs, mimetype="TRUST")

        self.assertTrue(att.store_fname, "docx must stream to the filestore")
        self.assertEqual(
            att.mimetype,
            "application/octet-stream",
            "TRUST mode must not correct the declared mimetype",
        )
        self.assertIn(
            "PROBE_TEXT_HERE",
            att.index_content or "",
            "a real docx must still be indexed despite a generic declared mimetype",
        )
