"""Regression tests for ``odoo.libs.numbers.float_utils.float_round``."""

import unittest

from odoo.libs.numbers.float_utils import float_round


class TestFloatRound(unittest.TestCase):
    def test_normalization_underflow_returns_zero(self):
        # a subnormal value divided by a large rounding factor underflows to 0
        # during normalization; must return 0.0, not raise from math.log2(0).
        self.assertEqual(float_round(1e-320, precision_rounding=1e20), 0.0)

    def test_zero_input(self):
        self.assertEqual(float_round(0.0, precision_rounding=0.01), 0.0)

    def test_normal_rounding(self):
        self.assertEqual(float_round(1.3, precision_rounding=0.5), 1.5)
        self.assertEqual(float_round(2.675, precision_digits=2), 2.68)


if __name__ == "__main__":
    unittest.main()
