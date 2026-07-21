import io
from pathlib import Path
from unittest import skipIf
from unittest.mock import patch

from werkzeug.datastructures import FileStorage

from odoo.tests.common import TransactionCase, tagged
from odoo.tools.misc import file_open

directory = Path(__file__).parent

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
