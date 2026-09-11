import unittest

from odoo.libs.colors.conversions import hex_to_rgb, lighten_hex


class TestHexToRgb(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(hex_to_rgb("#FF0000"), (255, 0, 0))
        self.assertEqual(hex_to_rgb("#00FF00"), (0, 255, 0))

    def test_optional_hash(self):
        self.assertEqual(hex_to_rgb("FF0000"), (255, 0, 0))

    def test_shorthand_is_expanded(self):
        self.assertEqual(hex_to_rgb("#FFF"), (255, 255, 255))
        self.assertEqual(hex_to_rgb("#f00"), (255, 0, 0))

    def test_malformed_still_raises(self):
        for value in ("", "#", "#12345", "nope", "#gg0000", "#1234567"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                hex_to_rgb(value)

    def test_alpha_forms_are_rejected_not_silently_dropped(self):
        for value in ("#1234", "#11223344"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                hex_to_rgb(value)


class TestLightenHex(unittest.TestCase):
    def test_shorthand_and_channel_rounding(self):
        self.assertEqual(lighten_hex("#000", 0.5), "#808080")
        self.assertEqual(lighten_hex("#EE4B39", 0.2), "#f16f61")

    def test_factor_is_clamped(self):
        self.assertEqual(lighten_hex("#AbC", -1), "#aabbcc")
        self.assertEqual(lighten_hex("#AbC", 2), "#ffffff")

    def test_invalid_and_alpha_input_is_rejected(self):
        for color in ("red", "#123456\n", "#12345680"):
            with self.subTest(color=color), self.assertRaises(ValueError):
                lighten_hex(color, 0.5)


if __name__ == "__main__":
    unittest.main()
