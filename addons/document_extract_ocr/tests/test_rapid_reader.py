import contextlib
from unittest.mock import patch

from odoo.libs.documents import EXPENSIVE, Document, known_readers
from odoo.tests.common import BaseCase, tagged

from odoo.addons.document_extract_ocr.models import rapid_reader


class _Output:
    def __init__(self, *txts):
        self.txts = txts or None


@tagged("post_install", "-at_install")
class TestRapidReader(BaseCase):
    def setUp(self):
        super().setUp()
        rapid_reader._get_engine.cache_clear()

    def tearDown(self):
        rapid_reader._get_engine.cache_clear()
        super().tearDown()

    @contextlib.contextmanager
    def _engine(self, engine):
        rapid_reader._get_engine.cache_clear()
        with patch.object(rapid_reader, "_get_engine", return_value=engine):
            yield

    def test_the_reader_is_offered_to_the_framework(self):
        self.assertIn("rapidocr_text", known_readers())

    def test_it_costs_more_than_every_reader_that_only_parses(self):
        self.assertEqual(rapid_reader.OcrText.cost, EXPENSIVE)

    def test_the_engine_is_built_once_and_kept(self):
        """Constructing it loads the PP-OCR weights, so a page must not pay for
        that again. The library is a hard requirement, so the only question left
        about the engine is how often it is built."""
        built = []

        class _Counted:
            def __init__(self):
                built.append(1)

            def __call__(self, image):
                return _Output("read")

        with patch.object(rapid_reader, "RapidOCR", _Counted):
            for _ in range(5):
                rapid_reader.read_page(b"page")

        self.assertEqual(len(built), 1)

    def test_an_engine_that_reads_nothing_yields_nothing(self):
        class _Blank:
            def __call__(self, image):
                return _Output()

        with self._engine(_Blank()):
            self.assertEqual(rapid_reader.read_page(b"page"), "")

    def test_what_the_engine_read_becomes_the_page_text(self):
        class _Reads:
            def __call__(self, image):
                return _Output(
                    "NO. DE SERVICIO: 970160701560",
                    "TOTAL A PAGAR",
                    "$139.86",
                )

        with self._engine(_Reads()):
            text = rapid_reader.read_page(b"page")

        self.assertIn("970160701560", text)
        self.assertIn("139.86", text)

    def test_a_scan_reaches_the_reader_through_the_source(self):
        class _Reads:
            def __call__(self, image):
                return _Output("READ FROM A SCAN")

        import pymupdf

        doc = pymupdf.open()
        doc.new_page()

        with self._engine(_Reads()):
            source = Document(doc.tobytes(), "application/pdf", read_up_to=EXPENSIVE)

            self.assertIn("READ FROM A SCAN", source.text)


@tagged("post_install", "-at_install")
class TestRapidReaderForReal(BaseCase):
    def _scan(self, lines=("NO. DE SERVICIO: 970160701560", "TOTAL A PAGAR $139.86")):
        import pymupdf

        doc = pymupdf.open()
        page = doc.new_page()
        for i, line in enumerate(lines):
            page.insert_text((40, 90 + i * 40), line, fontsize=18)
        with pymupdf.open(stream=doc.tobytes(), filetype="pdf") as rendered:
            return rendered[0].get_pixmap(dpi=200).tobytes("png")

    def test_it_reads_what_is_printed_on_the_page(self):
        text = rapid_reader.read_page(self._scan())

        self.assertIn("970160701560", text)
        self.assertIn("139.86", text)

    def test_a_blank_page_reads_as_nothing(self):
        import pymupdf

        doc = pymupdf.open()
        doc.new_page()
        with pymupdf.open(stream=doc.tobytes(), filetype="pdf") as rendered:
            blank = rendered[0].get_pixmap(dpi=150).tobytes("png")

        self.assertEqual(rapid_reader.read_page(blank).strip(), "")

    def test_a_scan_reaches_a_text_strategy_through_the_source(self):
        import pymupdf

        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((40, 90), "TOTAL A PAGAR $139.86", fontsize=18)
        with pymupdf.open(stream=doc.tobytes(), filetype="pdf") as flat:
            scan_png = flat[0].get_pixmap(dpi=200).tobytes("png")

        source = Document(scan_png, "image/png", "scan.png", read_up_to=EXPENSIVE)

        self.assertIn("139.86", source.text)
        self.assertTrue(source.provides("text"))
