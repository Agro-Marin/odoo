"""What a document can give, and how many times it is asked."""

import base64
import json

import pymupdf

from odoo.tests.common import BaseCase, tagged

from odoo.addons.document_extract.tools.source import DocumentSource

_PNG = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _pdf(pages=1, lines=10, text="TOTAL 139.86 CFE"):
    doc = pymupdf.open()
    for p in range(pages):
        page = doc.new_page()
        for i in range(lines):
            page.insert_text((40, 60 + i * 16), f"{text} p{p} l{i}")
    return doc.tobytes()


def _scan_pdf():
    doc = pymupdf.open()
    doc.new_page()
    return doc.tobytes()


@tagged("post_install", "-at_install")
class TestDocumentSource(BaseCase):
    def test_it_recognises_formats_without_being_told(self):
        for data, expected in (
            (_pdf(), "application/pdf"),
            (_PNG, "image/png"),
            (b"<root><a>1</a></root>", "application/xml"),
            (b'{"a": 1}', "application/json"),
        ):
            with self.subTest(expected=expected):
                self.assertEqual(DocumentSource(data).mimetype, expected)

    def test_a_declared_mimetype_wins_over_sniffing(self):
        source = DocumentSource(_PNG, "image/jpeg")

        self.assertEqual(source.mimetype, "image/jpeg")

    def test_it_reads_a_pdf_text_layer(self):
        source = DocumentSource(_pdf(), "application/pdf")

        self.assertIn("139.86", source.text)
        self.assertTrue(source.provides("text"))

    def test_a_scan_provides_images_but_no_text(self):
        source = DocumentSource(_scan_pdf(), "application/pdf")

        self.assertEqual(source.text, "")
        self.assertFalse(source.provides("text"))
        self.assertTrue(source.provides("images"))

    def test_it_renders_a_pdf_page_to_png(self):
        source = DocumentSource(_scan_pdf(), "application/pdf")

        images = source.images

        self.assertEqual(len(images), 1)
        self.assertTrue(images[0].startswith(b"\x89PNG\r\n\x1a\n"))

    def test_an_image_is_its_own_representation(self):
        source = DocumentSource(_PNG, "image/png")

        self.assertEqual(source.images, [_PNG])
        self.assertFalse(source.provides("text"))

    def test_it_parses_xml_into_a_tree_and_text(self):
        source = DocumentSource(b"<root><a>hello</a></root>", "application/xml")

        self.assertIsNotNone(source.tree)
        self.assertEqual(source.tree.tag, "root")
        self.assertIn("hello", source.text)
        self.assertTrue(source.provides("tree"))

    def test_xml_entities_are_not_resolved(self):
        """An extraction framework reads files it did not author."""
        xxe = (
            b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
            b"<r>&x;</r>"
        )

        source = DocumentSource(xxe, "application/xml")

        self.assertNotIn("root:", source.text)

    def test_it_decodes_json(self):
        source = DocumentSource(json.dumps({"total": 1.5}).encode(), "application/json")

        self.assertEqual(source.data_dict, {"total": 1.5})
        self.assertTrue(source.provides("data"))

    def test_it_accepts_base64_and_data_urls(self):
        encoded = base64.b64encode(_PNG).decode()

        for given in (encoded, f"data:image/png;base64,{encoded}"):
            with self.subTest(given=given[:20]):
                self.assertEqual(DocumentSource.of_bytes(given).mimetype, "image/png")

    def test_it_refuses_an_empty_document(self):
        with self.assertRaises(ValueError):
            DocumentSource(b"")

    def test_an_unknown_representation_is_an_error_not_a_false(self):
        """A typo in an extractor's `needs` must not read as "unavailable"."""
        source = DocumentSource(_PNG, "image/png")

        with self.assertRaises(ValueError):
            source.provides("txt")

    def test_each_representation_is_derived_once(self):
        """The property this whole class exists for.

        Two pieces of code needing the same text is the normal case, and the
        bug it caused before was invisible: correct output, twice the work.
        """
        source = DocumentSource(_pdf(pages=3), "application/pdf")
        opened = []
        real_open = pymupdf.open

        def counting_open(*args, **kwargs):
            opened.append(1)
            return real_open(*args, **kwargs)

        pymupdf.open = counting_open
        try:
            for _ in range(5):
                self.assertIn("139.86", source.text)
        finally:
            pymupdf.open = real_open

        self.assertEqual(len(opened), 1)

    def test_a_broken_pdf_reports_nothing_rather_than_raising(self):
        source = DocumentSource(b"%PDF-1.7 truncated", "application/pdf")

        self.assertEqual(source.text, "")
        self.assertEqual(source.images, [])
        self.assertEqual(source.page_count, 0)

    def test_a_long_text_layer_is_clamped(self):
        from odoo.addons.document_extract.tools import source as source_mod

        big = DocumentSource(_pdf(pages=40, lines=45), "application/pdf")

        self.assertLessEqual(len(big.text), source_mod.TEXT_MAX_CHARS)


@tagged("post_install", "-at_install")
class TestOcrFallback(BaseCase):
    """Making text out of a scan, and refusing to do it uninvited.

    This is the seam that lets a provider's regex template and a language model
    both work on scanned documents without either of them knowing OCR exists.
    It is tested with a reader that returns a fixed string, because what belongs
    here is when a reader is called -- an engine's accuracy is the engine's
    business and its own suite's.
    """

    def setUp(self):
        super().setUp()
        from odoo.addons.document_extract.tools import source as source_mod

        self._saved = list(source_mod._TEXT_READERS)
        self._calls = []

    def tearDown(self):
        from odoo.addons.document_extract.tools import source as source_mod

        source_mod._TEXT_READERS[:] = self._saved
        super().tearDown()

    def _reader(self, text="READ FROM THE PIXELS 139.86"):
        def read(page: bytes) -> str:
            self._calls.append(len(page))
            return text

        from odoo.addons.document_extract.tools import source as source_mod

        source_mod._TEXT_READERS[:] = [read]
        return read

    def test_a_scan_gets_text_when_the_caller_allows_it(self):
        self._reader()

        source = DocumentSource(_scan_pdf(), "application/pdf", allow_ocr=True)

        self.assertIn("139.86", source.text)
        self.assertTrue(source.provides("text"))
        self.assertEqual(len(self._calls), 1)

    def test_it_is_not_done_uninvited(self):
        """A posting path must not wait on an engine inside its transaction."""
        self._reader()

        source = DocumentSource(_scan_pdf(), "application/pdf")

        self.assertEqual(source.text, "")
        self.assertEqual(self._calls, [])

    def test_a_document_with_its_own_text_is_not_read_from_pixels(self):
        """The cheapest reading of a digital PDF is the one already there."""
        self._reader()

        source = DocumentSource(_pdf(), "application/pdf", allow_ocr=True)

        self.assertIn("139.86", source.text)
        self.assertEqual(self._calls, [])

    def test_an_image_is_read_from_its_pixels(self):
        self._reader()

        source = DocumentSource(_PNG, "image/png", allow_ocr=True)

        self.assertIn("139.86", source.text)

    def test_with_no_engine_installed_a_scan_simply_has_no_text(self):
        from odoo.addons.document_extract.tools import source as source_mod

        source_mod._TEXT_READERS[:] = []

        source = DocumentSource(_scan_pdf(), "application/pdf", allow_ocr=True)

        self.assertEqual(source.text, "")

    def test_an_engine_that_breaks_does_not_break_the_document(self):
        from odoo.addons.document_extract.tools import source as source_mod

        def explode(page):
            raise RuntimeError("model file missing")

        source_mod._TEXT_READERS[:] = [explode]

        source = DocumentSource(_scan_pdf(), "application/pdf", allow_ocr=True)

        self.assertEqual(source.text, "")

    def test_the_next_engine_is_tried_when_the_first_declines(self):
        from odoo.addons.document_extract.tools import source as source_mod

        source_mod._TEXT_READERS[:] = [lambda page: "", lambda page: "SECOND ENGINE"]

        source = DocumentSource(_scan_pdf(), "application/pdf", allow_ocr=True)

        self.assertEqual(source.text, "SECOND ENGINE")

    def test_it_is_read_once_however_often_it_is_asked_for(self):
        self._reader()
        source = DocumentSource(_scan_pdf(), "application/pdf", allow_ocr=True)

        for _ in range(4):
            source.text

        self.assertEqual(len(self._calls), 1)
