"""Regression tests for ``odoo.libs.colors.conversions.hex_to_rgb``."""

import unittest

from odoo.libs.colors.conversions import hex_to_rgb


class TestHexToRgb(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(hex_to_rgb("#FF0000"), (255, 0, 0))
        self.assertEqual(hex_to_rgb("#00FF00"), (0, 255, 0))

    def test_optional_hash(self):
        # Without '#' the old slices were off by one and returned a silently
        # wrong colour ((240, 0, 0) for 'FF0000'). The value is now parsed
        # correctly rather than rejected -- the '#' is optional in the CSS
        # forms these strings come from.
        self.assertEqual(hex_to_rgb("FF0000"), (255, 0, 0))

    def test_shorthand_is_expanded(self):
        # '#FFF' used to slice past the end and raise an opaque int() error.
        # CSS shorthand is legal input, so each digit is doubled instead.
        self.assertEqual(hex_to_rgb("#FFF"), (255, 255, 255))
        self.assertEqual(hex_to_rgb("#f00"), (255, 0, 0))

    def test_malformed_still_raises(self):
        # The point of validating is still met: anything that is not a hex
        # colour raises instead of returning a wrong tuple.
        for value in ("", "#", "#12345", "nope", "#gg0000", "#1234567"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                hex_to_rgb(value)


if __name__ == "__main__":
    unittest.main()
