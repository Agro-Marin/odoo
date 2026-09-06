import base64
import contextlib
from unittest.mock import patch

from odoo.libs.documents import CHEAP, Document, known_readers
from odoo.tests.common import BaseCase, tagged

from odoo.addons.extract_barcode.models import zxing_reader

QR_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAjoAAAI6AQAAAAAGM99tAAAFmklEQVR4nO2d3W3kOBCEq48C/EgBDsChaDJwSIcNyRmMQnEABqhHAxLqHvjXshfYw3p8x7spPoxHP/NBBMpEs5pNGXGTtv5xGw4gkEACCSSQQAIJJJBA/xeQlTYB63yYXXCYXTbL3/I5swl22SbYBUC+amZml+94IoEE+lqb8p/lCgDbI4DtgbYaQGz5HK3dxnWGcTUAQNgBAHbjJxJIoFu0IllsM7C8AIaYgOV6TAaEHevTDgJHvq9cZTus8h6xawIJ5NvyasYfcztMh2GdA0m+G5Z0mNkM8PqPPZFAAv1Gmz6diQSAQKzPb4blZYaVkCM07zt8dsHH65pAdw2qyo4EsAFY55SlzCWBJd7YZmC5HiWkxjblGMTre7yuCSQQsJrlKAPL6wQsKdAuW5G9XRAIbA/EkgKxJMAuOLI18k1PJJBAX2pZvH7wje+WP9andytXtzZcxx1c5wCefzRi1wS6axBIMg/DAALLzDDSjc/9Qr66pPoBBOZ2Ha9rAt01qCk7EAt3lI8USHJH1jjiDgD1FkSSVwTyGillCzQkCEWYsegZWcBZ6EXAWejXWK3rPGbnn7HeN17XBLprUFE2U2AdiwGSe4088lUA2evLg/Reh/o8ykvZAg0HKhIFgDw+I+6o47MPu8kE1LEdWc9+bB+vawLdNahlasJuCw8jAALbBGJ7BJb0uFvOrkfCEMuCEmKbyzKSGz+RQALdpJU4GyGHJN4bIVldEqCEJC2wLj+DohGBhgS5GWSeDyLuLbouE8p6tRskVfLtUMoWaDBQnUHmKWPw4XQz97qzXeJsevHL9RNoRJA3ObJtHXeXkKmmdtF9MQZj+zeoLomULdBgIJ+DbKNyPReqY33Sc/VG9jaES9kCDQeqrl+seRcALmdT3W6gzC9rNJInlNn6k7IFGg/0MQdZ543FDCkCTu3mflg9bilboBFBPlPjviWgpyRLmPJh3cgpZyNlCzQYqEUjfVFIaI713orCmqjzLZ8AUrZAg4Ga61dTM23e2EVdY5C+tKSa2ou8EYEGBbXs+jEB2+MOxB22pGPCwlL/aMsLQFfFHhPKzdsjLe/oMF7XBLprkN+VoYUkXOc3cDWA6wUgtrAbMO0AAusykh11z4abPpFAAt2kddevngl0NTX+XPX6XJOfLdCgoFO1WF080jPu3Qzx3nVfLRIVZws0Jsh5fW5JX08w/lTt7T6tiBJoVJB3/Zb6rSdp2Iohe7FNvaWX2EjZAo0KyrmYzSx7fesMmM2Bdun7QUXmQ/J1yrfwikN7sQo0JOgUjZAlu16W+XWPG3DLtdsFH3GP1zWB7hrkKnxr+NFkG2twUhb8+TrIj2UKUrZAY4F87XrLn/dxvBskLvPY1nH7urHxuibQXYNOq1hd1rwdptM5F6skv5hbyhZoMNCpwpfN2W57i7Q123VY9wO8D13G65pAdw1yrl8dkAO7iuvoDbiaGr8wEIqzBRoS1OJswGVlrvlarxarhy106TvuKBoRaERQq6lhzcWksuWqD05cXPKTshspW6DxQC3Obrv5RdahuVenp17X2+NssjonUrZAw4HgVZwAtFH5NKE8Jdt7dY3WjQg0KsjV1FQpe9va765z2mDEFeAoGhFoQJDPrp/DD18CmQBXl9A8FOUgBRodtFSDxL93qWfSzzmbnoP8xicSSKCvNRdOn9954N5J0wfzcs6v/1M0ItB/ArQkAOvTu9mfCeCPJ5LX+G7oeckfc3vVGAC7fPMTCSTQb7RP7/Bd55C/cH0iDPGYsLw+ENhmEJsh166vz28T10uT+HhdE+iuQR/f4cv1OaG8+CDv1PBAW2cY12eivNIXx4Ql3xZ2u/ETCSTQTdoHb6S/5KBOHnG2/oC+GEr7+gk0LMj463v+TlvH65pAAgkkkEACCSSQQAL9a6C/ACAX/31gzYpwAAAAAElFTkSuQmCC"
)

SAT_URL = (
    "https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx?"
    "&id=B92C34C7-81B3-489E-86DC-55843EF905FE&re=CFE370814QI0"
    "&rr=XAXX010101000&tt=139.86&fe=Kx8vTw=="
)


class _Symbol:
    def __init__(self, text):
        self.text = text


class _TwoPages:
    """A document already rendered, so the reader is tested and not the renderer."""

    name = "two_pages.pdf"
    images = (QR_PNG, QR_PNG)


@tagged("post_install", "-at_install")
class TestZxingReader(BaseCase):
    """What the reader does with whatever the decoder hands back.

    The decoder is a hard requirement, so these stand a fake in for it only to
    reach pages a real fixture cannot produce -- a page that decodes twice to
    the same payload, and a page whose decoding raises.
    """

    @contextlib.contextmanager
    def _decoder(self, decode):
        with patch.object(zxing_reader.zxingcpp, "read_barcodes", decode):
            yield

    def test_the_reader_is_offered_to_the_framework(self):
        self.assertIn("zxing_barcodes", known_readers())

    def test_decoding_a_page_needs_no_permission_to_spend(self):
        """Rendering is what a page costs, and `images` is already paid for by
        whoever asked for it. Registered above the default ceiling, a printed
        CFDI's QR would go unread on every document nobody thought to ask."""
        self.assertLessEqual(zxing_reader.Barcodes.cost, CHEAP)

    def test_what_the_decoder_finds_becomes_the_payloads(self):
        with self._decoder(lambda image: [_Symbol(SAT_URL), _Symbol("OTHER")]):
            found = zxing_reader.read_page(QR_PNG)

        self.assertEqual(found, [SAT_URL, "OTHER"])

    def test_barcodes_reach_the_source_and_are_not_repeated(self):
        with self._decoder(lambda image: [_Symbol(SAT_URL), _Symbol(SAT_URL)]):
            source = Document(QR_PNG, "image/png", "scan.png")

            self.assertEqual(source.barcodes, [SAT_URL])
            self.assertTrue(source.provides("barcodes"))

    def test_a_decoder_that_breaks_does_not_break_the_document(self):
        def explode(image):
            raise RuntimeError("decoder blew up")

        with self._decoder(explode):
            source = Document(QR_PNG, "image/png", "scan.png")

            self.assertEqual(source.barcodes, [])

    def test_a_page_that_breaks_does_not_lose_the_pages_that_did_not(self):
        seen = []

        def explode_on_the_first(image):
            seen.append(image)
            if len(seen) == 1:
                raise RuntimeError("decoder blew up")
            return [_Symbol(SAT_URL)]

        with self._decoder(explode_on_the_first):
            found = zxing_reader.Barcodes().read(_TwoPages())

        self.assertEqual(found, [SAT_URL])


@tagged("post_install", "-at_install")
class TestZxingReaderForReal(BaseCase):
    def test_it_decodes_an_actual_qr(self):
        found = zxing_reader.read_page(QR_PNG)

        self.assertEqual(found, [SAT_URL])

    def test_a_page_with_no_code_on_it_decodes_to_nothing(self):
        import pymupdf

        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((40, 60), "a page with words and no code")
        rendered = doc[0].get_pixmap(dpi=150).tobytes("png")

        self.assertEqual(zxing_reader.read_page(rendered), [])

    def test_a_code_survives_being_printed_and_rendered(self):
        import pymupdf

        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((40, 60), "COMISION FEDERAL DE ELECTRICIDAD")
        page.insert_image(pymupdf.Rect(400, 500, 520, 620), stream=QR_PNG)
        source = Document(doc.tobytes(), "application/pdf", "printed.pdf")

        self.assertEqual(source.barcodes, [SAT_URL])
