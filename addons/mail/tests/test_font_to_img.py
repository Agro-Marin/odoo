from io import BytesIO

from PIL import Image

from odoo.tests.common import HttpCase, tagged
from odoo.tools.misc import file_open


@tagged("-at_install", "post_install")
class TestFontToImg(HttpCase):
    def test_font_to_img(self):
        # This test was introduced because the play button was cropped in noble following some adaptation.
        # This test is able to reproduce the issue and ensure that the expected result is the right one
        # comparing image is not ideal, but this should work in most case, maybe adapted if the font is changed.
        # Uses fa-play (U+F04B = 61515), the real play glyph in FA7 fa-solid-900.
        # The former code 61802 (U+F16A) was a play button in older FontAwesome
        # but is a placeholder box in FA7 — fragile to golden-test and not a
        # "play button". Size is the glyph's bbox for this font + Pillow.

        response = self.url_open(
            "/mail/font_to_img/61515/rgb(0,143,140)/rgb(255,255,255)/190x200"
        )

        img = Image.open(BytesIO(response.content))
        self.assertEqual(
            img.size,
            (175, 200),
            "Width depends on glyph bbox in FA7 fa-solid-900.woff2 with Pillow 12+",
        )
        # Image is a play button
        img_reference = Image.open(file_open("mail/tests/play.png", "rb"))
        self.assertEqual(img, img_reference, "Result image should be the play button")

    def test_font_to_img_out_of_range_codepoint(self):
        """A decimal icon outside the Unicode range must 404, not 500: chr()
        would raise ValueError on this unauthenticated (auth="none") route."""
        response = self.url_open("/mail/font_to_img/99999999999")
        self.assertEqual(
            response.status_code,
            404,
            "out-of-range code point should be a clean 404, not a 500",
        )
