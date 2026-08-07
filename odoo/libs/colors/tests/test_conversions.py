import unittest

from odoo.libs.colors.conversions import hex_to_rgb


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


if __name__ == "__main__":
    unittest.main()
