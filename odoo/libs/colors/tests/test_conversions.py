"""Regression tests for ``odoo.libs.colors.conversions.hex_to_rgb``."""

import unittest

from odoo.libs.colors.conversions import hex_to_rgb


class TestHexToRgb(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(hex_to_rgb("#FF0000"), (255, 0, 0))
        self.assertEqual(hex_to_rgb("#00FF00"), (0, 255, 0))

    def test_missing_hash_raises(self):
        # without '#' the slices are off by one and returned a wrong colour.
        with self.assertRaises(ValueError):
            hex_to_rgb("FF0000")

    def test_shorthand_raises(self):
        # '#FFF' shorthand sliced past the end and raised an opaque int() error.
        with self.assertRaises(ValueError):
            hex_to_rgb("#FFF")


if __name__ == "__main__":
    unittest.main()
