import base64
import json

import pymupdf

from odoo.libs.documents import (
    EXPENSIVE,
    TEXT,
    TEXT_MAX_CHARS,
    BaseReader,
    Document,
    register_reader,
)
from odoo.libs.documents import readers as libs_readers
from odoo.tests.common import BaseCase, tagged

from odoo.addons.document_extract.tools import PAGED

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
                self.assertEqual(Document(data).mimetype, expected)

    def test_a_declared_mimetype_wins_over_sniffing(self):
        source = Document(_PNG, "image/jpeg")

        self.assertEqual(source.mimetype, "image/jpeg")

    def test_it_reads_a_pdf_text_layer(self):
        source = Document(_pdf(), "application/pdf")

        self.assertIn("139.86", source.text)
        self.assertTrue(source.provides("text"))

    def test_a_scan_provides_images_but_no_text(self):
        source = Document(_scan_pdf(), "application/pdf")

        self.assertEqual(source.text, "")
        self.assertFalse(source.provides("text"))
        self.assertTrue(source.provides("images"))

    def test_it_renders_a_pdf_page_to_png(self):
        source = Document(_scan_pdf(), "application/pdf")

        images = source.images

        self.assertEqual(len(images), 1)
        self.assertTrue(images[0].startswith(b"\x89PNG\r\n\x1a\n"))

    def test_an_image_is_its_own_representation(self):
        source = Document(_PNG, "image/png")

        self.assertEqual(source.images, [_PNG])
        self.assertFalse(source.provides("text"))

    def test_it_parses_xml_into_a_tree_and_text(self):
        source = Document(b"<root><a>hello</a></root>", "application/xml")

        self.assertIsNotNone(source.tree)
        self.assertEqual(source.tree.tag, "root")
        self.assertIn("hello", source.text)
        self.assertTrue(source.provides("tree"))

    def test_xml_entities_are_not_resolved(self):
        xxe = (
            b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
            b"<r>&x;</r>"
        )

        source = Document(xxe, "application/xml")

        self.assertNotIn("root:", source.text)

    def test_it_decodes_json(self):
        source = Document(json.dumps({"total": 1.5}).encode(), "application/json")

        self.assertEqual(source.data_dict, {"total": 1.5})
        self.assertTrue(source.provides("data"))

    def test_it_accepts_base64_and_data_urls(self):
        encoded = base64.b64encode(_PNG).decode()

        for given in (encoded, f"data:image/png;base64,{encoded}"):
            with self.subTest(given=given[:20]):
                self.assertEqual(Document.of_bytes(given).mimetype, "image/png")

    def test_it_refuses_an_empty_document(self):
        with self.assertRaises(ValueError):
            Document(b"")

    def test_an_unknown_representation_is_an_error_not_a_false(self):
        source = Document(_PNG, "image/png")

        with self.assertRaises(ValueError):
            source.provides("txt")

    def test_each_representation_is_derived_once(self):
        source = Document(_pdf(pages=3), "application/pdf")
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
        from odoo.addons.document_extract.tools import readers as source_mod

        source = Document(b"%PDF-1.7 truncated", "application/pdf")

        self.assertEqual(source.text, "")
        self.assertEqual(source.images, [])
        self.assertEqual(source_mod.page_count(source), 0)

    def test_a_long_text_layer_is_clamped(self):
        big = Document(_pdf(pages=40, lines=45), "application/pdf")

        self.assertLessEqual(len(big.text), TEXT_MAX_CHARS)


@tagged("post_install", "-at_install")
class TestReadingPagesCostsMore(BaseCase):
    """What a reader registered above the default ceiling can and cannot do.

    The engine itself ships in `document_extract_ocr`, which is optional and in
    another repository. What is pinned here is the contract every such reader
    answers to, with a stub standing in for the engine: it is not run uninvited,
    it is not run on a document that already has text, and it is what a scan
    falls through to.
    """

    def setUp(self):
        super().setUp()
        self.pages_read = []
        test = self

        class _StubEngine(BaseReader):
            name = "test_page_text"
            mimetypes = PAGED
            yields = (TEXT,)
            cost = EXPENSIVE

            def __init__(self, text="READ FROM THE PIXELS 139.86", boom=False):
                self.text = text
                self.boom = boom

            def read(self, document):
                if self.boom:
                    raise RuntimeError("model file missing")
                test.pages_read.extend(document.images)
                return self.text

        self.Engine = _StubEngine

    def _install(self, *engines):
        for engine in engines:
            register_reader(engine)
        self.addCleanup(self._forget, engines)
        return engines

    def _forget(self, engines):
        for bucket in libs_readers._READERS.values():
            for engine in engines:
                while engine in bucket:
                    bucket.remove(engine)

    def test_a_scan_gets_text_when_the_caller_pays_for_it(self):
        self._install(self.Engine())

        source = Document(_scan_pdf(), "application/pdf", read_up_to=EXPENSIVE)

        self.assertIn("139.86", source.text)
        self.assertTrue(source.provides("text"))
        self.assertEqual(len(self.pages_read), 1)

    def test_it_is_not_done_uninvited(self):
        self._install(self.Engine())

        source = Document(_scan_pdf(), "application/pdf")

        self.assertEqual(source.text, "")
        self.assertEqual(self.pages_read, [])

    def test_the_ceiling_can_be_raised_on_a_document_already_read(self):
        """Escalation reaches a document that has already answered emptily.

        The cascade runs a free pass before it decides a document is worth
        paying for, so by the time anything raises the ceiling the text has
        been asked for and cached. A ceiling that only counted before the
        first read would be a ceiling nothing could ever raise."""
        self._install(self.Engine())
        source = Document(_scan_pdf(), "application/pdf")

        self.assertEqual(source.text, "")
        self.assertEqual(self.pages_read, [])

        source.options["read_up_to"] = EXPENSIVE

        self.assertIn("139.86", source.text)
        self.assertEqual(len(self.pages_read), 1)

    def test_raising_the_ceiling_does_not_re_read_what_was_already_read(self):
        self._install(self.Engine())
        source = Document(_pdf(), "application/pdf")

        self.assertIn("139.86", source.text)
        source.options["read_up_to"] = EXPENSIVE

        self.assertIn("139.86", source.text)
        self.assertEqual(self.pages_read, [])

    def test_a_document_with_its_own_text_is_not_read_from_pixels(self):
        self._install(self.Engine())

        source = Document(_pdf(), "application/pdf", read_up_to=EXPENSIVE)

        self.assertIn("139.86", source.text)
        self.assertEqual(self.pages_read, [])

    def test_an_image_is_read_from_its_pixels(self):
        self._install(self.Engine())

        source = Document(_PNG, "image/png", read_up_to=EXPENSIVE)

        self.assertIn("139.86", source.text)

    def test_with_no_engine_installed_a_scan_simply_has_no_text(self):
        source = Document(_scan_pdf(), "application/pdf", read_up_to=EXPENSIVE)

        self.assertEqual(source.text, "")

    def test_an_engine_that_breaks_does_not_break_the_document(self):
        self._install(self.Engine(boom=True))

        source = Document(_scan_pdf(), "application/pdf", read_up_to=EXPENSIVE)

        self.assertEqual(source.text, "")

    def test_the_next_engine_is_tried_when_the_first_declines(self):
        self._install(self.Engine(text=""), self.Engine(text="SECOND ENGINE"))

        source = Document(_scan_pdf(), "application/pdf", read_up_to=EXPENSIVE)

        self.assertEqual(source.text, "SECOND ENGINE")

    def test_it_is_read_once_however_often_it_is_asked_for(self):
        self._install(self.Engine())
        source = Document(_scan_pdf(), "application/pdf", read_up_to=EXPENSIVE)

        for _ in range(4):
            source.text

        self.assertEqual(len(self.pages_read), 1)
