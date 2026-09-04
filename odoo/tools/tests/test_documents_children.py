import io
import unittest

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
        """The point of the representation rather than a helper returning bytes:
        whatever the layer can do to a document it can do to one that arrived
        inside another."""
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
        """`_derive` logs a reader that raises and moves on, so a mislabelled
        document is an empty answer rather than a traceback out of a property."""
        self.assertEqual(
            Document(b"not a pdf at all", "application/pdf", "x.pdf").children, []
        )

    def test_an_embedded_file_with_no_content_is_dropped(self):
        """`Document` refuses empty bytes, so a zero-length attachment is a name
        with nothing to read rather than a document."""
        pdf = _pdf_carrying(("empty.xml", b""), ("real.xml", b"<a/>"))

        children = Document(pdf, "application/pdf", "bill.pdf").children

        self.assertEqual([c.name for c in children], ["real.xml"])
