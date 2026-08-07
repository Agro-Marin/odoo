import unittest

from odoo.tools.formatting import format_decimalized_number as fdn


class TestFormatDecimalizedNumber(unittest.TestCase):
    def test_documented_examples(self):
        self.assertEqual(fdn(123_456.789), "123.5k")
        self.assertEqual(fdn(123_000.789), "123k")
        self.assertEqual(fdn(-123_456.789), "-123.5k")
        self.assertEqual(fdn(0.789), "0.8")

    def test_rounding_up_promotes_the_unit(self):
        self.assertEqual(fdn(999.99), "1k")
        self.assertEqual(fdn(999_999.9), "1M")
        self.assertEqual(fdn(999_999_999.0), "1G")

    def test_values_just_below_the_boundary_keep_their_unit(self):
        self.assertEqual(fdn(999.94), "999.9")
        self.assertEqual(fdn(999_940.0), "999.9k")

    def test_negative_values_promote_too(self):
        self.assertEqual(fdn(-999_999.9), "-1M")

    def test_zero_and_small(self):
        self.assertEqual(fdn(0), "0")
        self.assertEqual(fdn(1), "1")
        self.assertEqual(fdn(-1), "-1")

    def test_tera_is_the_cap(self):
        self.assertEqual(fdn(1e12), "1T")
        self.assertEqual(fdn(1e15), "1000T")

    def test_decimal_argument_is_honoured(self):
        self.assertEqual(fdn(123_456.789, decimal=0), "123k")
        self.assertEqual(fdn(123_456.789, decimal=2), "123.46k")

    def test_exact_boundaries(self):
        self.assertEqual(fdn(1000), "1k")
        self.assertEqual(fdn(1_000_000), "1M")
        self.assertEqual(fdn(1_000_000_000), "1G")


if __name__ == "__main__":
    unittest.main()
