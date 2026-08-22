# Part of Odoo. See LICENSE file for full copyright and licensing details.
import io

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from odoo.tests import TransactionCase
from odoo.tools.pdf import PdfFileReader


def _pdf_of(page_labels):
    """A PDF carrying one page per label, each stamping its label as text."""
    buf = io.BytesIO()
    canvas = Canvas(buf, pagesize=A4)
    for label in page_labels:
        canvas.drawString(20, 20, label)
        canvas.showPage()
    canvas.save()
    return buf.getvalue()


class TestCoverPage(TransactionCase):
    """What _add_cover_page does to the page order.

    Nothing covered this before, which is how the method kept a name stating
    the wrong end of it: it was ``_append_cover_page`` while the cover it adds
    goes FIRST. The name is fixed; these pin the behaviour the name now claims,
    so the next reader does not have to take either on trust.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        partner = cls.env["res.partner"].create(
            {
                "name": "Cover Test",
                "street": "1 Rue Test",
                "zip": "75001",
                "city": "Paris",
            }
        )
        cls.letter = cls.env["snailmail.letter"].create(
            {
                "model": partner._name,
                "res_id": partner.id,
                "partner_id": partner.id,
            }
        )

    def _pages(self, pdf_bin):
        return len(PdfFileReader(io.BytesIO(pdf_bin)).pages)

    def test_the_cover_page_is_added_at_the_front(self):
        body = _pdf_of(["body-1", "body-2"])
        merged = self.letter._add_cover_page(body)

        self.assertEqual(self._pages(merged), 3, "one cover page was added")
        first = PdfFileReader(io.BytesIO(merged)).pages[0].extract_text()
        self.assertNotIn(
            "body-1",
            first,
            "the cover is the first page; the body follows it. A method that "
            "appended would put the body first.",
        )
        last = PdfFileReader(io.BytesIO(merged)).pages[-1].extract_text()
        self.assertIn("body-2", last, "the body keeps its own order behind the cover")

    def test_duplex_adds_a_blank_page_behind_the_cover(self):
        body = _pdf_of(["body-1"])
        self.letter.duplex = True

        merged = self.letter._add_cover_page(body)

        self.assertEqual(
            self._pages(merged),
            3,
            "cover, then the blank buffer page that keeps the body from "
            "printing on the back of the cover, then the body",
        )
