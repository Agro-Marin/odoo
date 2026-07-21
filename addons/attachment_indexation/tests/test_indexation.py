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
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('word/document.xml', document_xml)
    return buf.getvalue()

try:
    from pdfminer.pdfinterp import PDFResourceManager
except ImportError:
    PDFResourceManager = None


@tagged('post_install', '-at_install')
class TestCaseIndexation(TransactionCase):

    @skipIf(PDFResourceManager is None, "pdfminer not installed")
    def test_attachment_pdf_indexation(self):
        with file_open(str(directory / 'files' / 'test_content.pdf'), 'rb') as file:
            pdf = file.read()
            text = self.env['ir.attachment']._index(pdf, 'application/pdf')
            self.assertEqual(text, 'TestContent!!', 'the index content should be correct')

    def test_docx_indexation_happy_path(self):
        """A well-formed .docx parses normally and its text is extracted."""
        document_xml = (
            b'<?xml version="1.0"?>'
            b'<w:document xmlns:w="ns"><w:body><w:p>Hello</w:p></w:body></w:document>'
        )
        text = self.env['ir.attachment']._index_docx(_build_docx(document_xml))
        self.assertIn('Hello', text)

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
        text = self.env['ir.attachment']._index_docx(_build_docx(document_xml))
        self.assertEqual(text, '', "entity declarations must not be substituted into the index")

    def test_docx_indexation_skips_oversized_entry(self):
        """A word/document.xml entry larger than _INDEX_MAX_BYTES must be
        skipped before parsing, not read/parsed in full (zip-bomb guard)."""
        Att = self.env['ir.attachment']
        padding = b'<!-- ' + b'a' * (Att._INDEX_MAX_BYTES + 1) + b' -->'
        document_xml = (
            b'<?xml version="1.0"?>'
            b'<w:document xmlns:w="ns">' + padding +
            b'<w:body><w:p>Hello</w:p></w:body></w:document>'
        )
        text = Att._index_docx(_build_docx(document_xml))
        self.assertEqual(text, '', "an oversized entry must be skipped, not parsed")

    def test_index_read_size_documents_read_full(self):
        """Parsed document mimetypes request a full read-back from the streaming
        create path, text keeps its bounded prefix, and unindexable media skips
        the read so it streams flat."""
        Att = self.env['ir.attachment']
        self.assertIsNone(Att._index_read_size('application/pdf'))
        self.assertIsNone(Att._index_read_size(
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'))
        self.assertEqual(Att._index_read_size('text/plain'), Att._INDEX_MAX_BYTES)
        self.assertEqual(Att._index_read_size('video/mp4'), 0)
        self.assertEqual(Att._index_read_size('application/octet-stream'), 0)

    @skipIf(PDFResourceManager is None, "pdfminer not installed")
    def test_streamed_pdf_reads_full_content_and_indexes(self):
        """A PDF uploaded over the streaming path is read back in full and indexed."""
        # A capped read would parse a large PDF from a truncated prefix and lose its index.
        Att = self.env['ir.attachment']
        with file_open(str(directory / 'files' / 'test_content.pdf'), 'rb') as f:
            pdf = f.read()

        read_sizes = []
        model_cls = type(Att)
        real_read = model_cls._file_read

        def read_spy(model, fname, size=None):
            read_sizes.append(size)
            return real_read(model, fname, size=size)

        with patch.object(model_cls, '_file_read', read_spy):
            fs = FileStorage(stream=io.BytesIO(pdf), filename='c.pdf',
                             content_type='application/pdf')
            att = Att._from_request_file(fs, mimetype='TRUST')

        self.assertTrue(att.store_fname, "PDF must stream to the filestore")
        self.assertEqual(att.index_content, 'TestContent!!')
        # the index read-back asked for the WHOLE file (size=None), never the
        # bounded prefix the pre-seam code used.
        self.assertIn(None, read_sizes,
                      "streamed PDF index read must be unbounded")
        self.assertNotIn(Att._INDEX_MAX_BYTES, read_sizes,
                         "must not cap the document index read at the prefix")
