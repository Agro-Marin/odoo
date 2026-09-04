import io
import subprocess
import sys
import unittest
from pathlib import Path

from odoo.libs.documents import CHILDREN, Document, get_readers
from odoo.tools.pdf import OdooPdfFileWriter


def _pdf_carrying(*embedded):
    writer = OdooPdfFileWriter()
    writer.add_blank_page(width=200, height=200)
    for name, data in embedded:
        writer.add_attachment(name, data)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class TestPdfEmbeddedFiles(unittest.TestCase):
    def test_the_reader_is_registered_for_pdf(self):
        names = [r.name for r in get_readers("application/pdf", CHILDREN)]

        self.assertIn("pdf_embedded_files", names)

    def test_an_embedded_file_becomes_a_document_of_its_own(self):
        pdf = _pdf_carrying(
            ("factur-x.xml", b"<Invoice><Total>139.86</Total></Invoice>")
        )

        (child,) = Document(pdf, "application/pdf", "bill.pdf").children

        self.assertEqual(child.name, "factur-x.xml")
        self.assertEqual(child.mimetype, "application/xml")
        self.assertIsNotNone(child.tree)

    def test_the_child_is_read_like_any_other_document(self):
        # A representation rather than a helper returning bytes: whatever the
        # layer can do to a document it can do to one that came inside another.
        pdf = _pdf_carrying(("data.csv", b"ref,total\nINV/1,139.86\n"))

        (child,) = Document(pdf, "application/pdf", "bill.pdf").children

        self.assertEqual(child.rows, [["ref", "total"], ["INV/1", "139.86"]])

    def test_every_embedded_file_comes_back(self):
        pdf = _pdf_carrying(
            ("a.xml", b"<a/>"), ("b.json", b'{"b": 1}'), ("c.txt", b"c")
        )

        children = Document(pdf, "application/pdf", "bill.pdf").children

        self.assertEqual(sorted(c.name for c in children), ["a.xml", "b.json", "c.txt"])

    def test_a_pdf_carrying_nothing_has_no_children(self):
        self.assertEqual(
            Document(_pdf_carrying(), "application/pdf", "x.pdf").children, []
        )

    def test_a_document_that_is_not_a_pdf_has_no_children(self):
        self.assertEqual(Document(b"<a/>", name="x.xml").children, [])

    def test_bytes_that_are_not_a_pdf_do_not_raise(self):
        # `_derive` logs a reader that raises, so a mislabelled document is an
        # empty answer rather than a traceback out of a property.
        self.assertEqual(
            Document(b"not a pdf at all", "application/pdf", "x.pdf").children, []
        )

    def test_an_embedded_file_with_no_content_is_dropped(self):
        # `Document` refuses empty bytes, so a zero-length attachment is a name
        # with nothing to read rather than a document.
        pdf = _pdf_carrying(("empty.xml", b""), ("real.xml", b"<a/>"))

        children = Document(pdf, "application/pdf", "bill.pdf").children

        self.assertEqual([c.name for c in children], ["real.xml"])


class TestTheReaderCostsNothingToRegister(unittest.TestCase):
    def test_importing_odoo_tools_does_not_pull_in_pypdf(self):
        # A subprocess, because this module imports `odoo.tools.pdf` itself for
        # the writer that builds its fixtures; in-process this would read its
        # own import. Asserted rather than commented because the comment that
        # explained the deferral did not survive the file being written.
        repo = Path(__file__).resolve().parents[3]
        probe = (
            "import odoo.tools, sys; "
            "print('pypdf' in sys.modules, 'odoo.tools.pdf' in sys.modules)"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            check=False,
            capture_output=True,
            text=True,
            cwd=repo,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ["False", "False"])

    def test_the_reader_registers_all_the_same(self):
        # Deferring the import must not defer the registration, or the reader
        # is absent exactly when it is wanted.
        self.assertIn(
            "pdf_embedded_files",
            [r.name for r in get_readers("application/pdf", CHILDREN)],
        )
