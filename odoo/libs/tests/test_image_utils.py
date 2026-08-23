import base64
import io
import unittest

from PIL import Image

from odoo.libs.image.utils import (
    ImageDecodeError,
    ImageProcess,
    average_dominant_color,
    base64_to_image,
    binary_to_image,
    is_image_size_above,
)

SVG = b"<svg xmlns='http://www.w3.org/2000/svg'><rect width='1' height='1'/></svg>"
WEBP = b"RIFF" + b"\x00" * 4 + b"WEBPVP8 " + b"\x00" * 20


class TestOriginalFormatAlwaysDefined(unittest.TestCase):
    def test_empty_source(self):
        self.assertEqual(ImageProcess(b"").original_format, "")

    def test_falsy_source(self):
        self.assertEqual(ImageProcess(None).original_format, "")

    def test_svg_source(self):
        self.assertEqual(ImageProcess(SVG).original_format, "")

    def test_webp_source(self):
        self.assertEqual(ImageProcess(WEBP).original_format, "")

    def test_svg_passthrough_still_works(self):
        self.assertEqual(ImageProcess(SVG).image_quality(), SVG)

    def test_chaining_on_svg_is_a_noop(self):
        processed = ImageProcess(SVG).resize(64, 64).image_quality()
        self.assertEqual(processed, SVG)


class TestAverageDominantColorDegenerateInput(unittest.TestCase):
    def test_empty_list(self):
        with self.assertRaises(ValueError) as ctx:
            average_dominant_color([])
        self.assertIn("non-empty", str(ctx.exception))

    def test_all_zero_counts(self):
        with self.assertRaises(ValueError) as ctx:
            average_dominant_color([(0, (1, 2, 3, 255))])
        self.assertIn("non-zero count", str(ctx.exception))

    def test_feedback_loop_shape(self):
        colors = [(10, (255, 0, 0, 255)), (5, (0, 0, 255, 255))]
        primary, remaining = average_dominant_color(colors)
        self.assertEqual(len(primary), 3)
        while remaining:
            _next_color, remaining = average_dominant_color(remaining)


class TestAverageDominantColorStillCorrect(unittest.TestCase):
    def test_single_color(self):
        self.assertEqual(
            average_dominant_color([(5, (10, 20, 30, 255))]), ((10, 20, 30), [])
        )

    def test_similar_colors_grouped(self):
        primary, remaining = average_dominant_color(
            [(100, (10, 10, 10, 255)), (1, (250, 250, 250, 255))]
        )
        self.assertEqual(remaining, [(1, (250, 250, 250, 255))])
        self.assertEqual(primary, (10, 10, 10))

    def test_mitigate_caps_brightness(self):
        primary, _ = average_dominant_color([(1, (255, 255, 255, 255))], mitigate=175)
        self.assertTrue(all(band <= 175 for band in primary))


if __name__ == "__main__":
    unittest.main()


def _png(mode: str, size: tuple[int, int] = (4, 4), color=(1, 2, 3)) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, color if mode in ("RGB", "RGBA") else 128).save(
        buf, format="PNG"
    )
    return buf.getvalue()


class TestColorizeAcceptsEveryMode(unittest.TestCase):
    """The source doubles as its own paste mask, and PIL is picky about masks.

    It accepts one only in "1"/"L"/"LA"/"RGBA".  An RGB source -- the commonest
    mode there is -- raised `ValueError: bad transparency mask`, and a palette
    image did too, because a "P" image keeps its transparency in `info` rather
    than in a band.
    """

    def test_every_mode_survives(self):
        for mode in ("RGB", "RGBA", "L", "P", "1"):
            with self.subTest(mode=mode):
                processed = ImageProcess(_png(mode)).colorize((10, 20, 30))
                image = processed.image
                assert image is not False, "a PNG must decode"
                self.assertEqual(image.mode, "RGB")
                self.assertEqual(processed.operations_count, 1)

    def test_a_transparent_pixel_still_shows_the_fill(self):
        buf = io.BytesIO()
        Image.new("RGBA", (2, 2), (255, 0, 0, 0)).save(buf, format="PNG")
        image = ImageProcess(buf.getvalue()).colorize((7, 8, 9)).image
        assert image is not False, "a PNG must decode"
        self.assertEqual(image.getpixel((0, 0)), (7, 8, 9))

    def test_an_opaque_pixel_still_covers_the_fill(self):
        buf = io.BytesIO()
        Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(buf, format="PNG")
        image = ImageProcess(buf.getvalue()).colorize((7, 8, 9)).image
        assert image is not False, "a PNG must decode"
        self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))


class TestDecodeFailuresShareOneError(unittest.TestCase):
    """One message, one exception type, from all three entry points.

    The try/except and its message were written out three times; the third copy
    also had to catch `binascii.Error`, which only the base64 door can raise.
    """

    def test_binary_to_image(self):
        with self.assertRaises(ImageDecodeError):
            binary_to_image(b"not an image")

    def test_base64_to_image_with_undecodable_image(self):
        with self.assertRaises(ImageDecodeError):
            base64_to_image(base64.b64encode(b"nope"))

    def test_base64_to_image_with_malformed_base64(self):
        with self.assertRaises(ImageDecodeError):
            base64_to_image("!!!not base64!!!")

    def test_image_process_constructor(self):
        with self.assertRaises(ImageDecodeError):
            ImageProcess(b"not an image")


class TestIsImageSizeAbove(unittest.TestCase):
    def test_compares_dimensions(self):
        big, small = (
            base64.b64encode(_png("RGB", (8, 8))),
            base64.b64encode(_png("RGB", (4, 4))),
        )
        self.assertTrue(is_image_size_above(big, small))
        self.assertFalse(is_image_size_above(small, big))
        self.assertFalse(is_image_size_above(big, big))

    def test_svg_and_falsy_sources_are_never_above(self):
        png = base64.b64encode(_png("RGB"))
        self.assertFalse(is_image_size_above(b"P...", png))
        self.assertFalse(is_image_size_above(png, b"P..."))
        self.assertFalse(is_image_size_above(None, png))
        self.assertFalse(is_image_size_above(png, b""))
