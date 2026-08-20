from io import BytesIO

from PIL import Image

from odoo.tests.common import HttpCase, tagged
from odoo.tools.misc import file_open


@tagged("-at_install", "post_install")
class TestFontToImg(HttpCase):
    def test_font_to_img(self):
        response = self.url_open(
            "/mail/font_to_img/61515/rgb(0,143,140)/rgb(255,255,255)/190x200"
        )

        img = Image.open(BytesIO(response.content))
        self.assertEqual(
            img.size,
            (175, 200),
            "Width depends on glyph bbox in FA7 fa-solid-900.woff2 with Pillow 12+",
        )
        img_reference = Image.open(file_open("mail/tests/play.png", "rb"))
        self.assertEqual(img, img_reference, "Result image should be the play button")

    def test_font_to_img_out_of_range_codepoint(self):
        response = self.url_open("/mail/font_to_img/99999999999")
        self.assertEqual(
            response.status_code,
            404,
            "out-of-range code point should be a clean 404, not a 500",
        )

    def test_font_to_img_caps_the_glyph_count(self):
        response = self.url_open("/mail/font_to_img/" + "W" * 400 + "/%23000/512x512")
        self.assertEqual(
            response.status_code,
            404,
            "a glyph string past the cap must be refused before it is rendered",
        )
