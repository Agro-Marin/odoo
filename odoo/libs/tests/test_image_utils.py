import unittest

from odoo.libs.image.utils import ImageProcess, average_dominant_color

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
