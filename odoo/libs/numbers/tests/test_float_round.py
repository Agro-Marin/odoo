"""Regression tests for ``odoo.libs.numbers.float_utils.float_round``."""

import random
import unittest
from decimal import (
    ROUND_DOWN,
    ROUND_HALF_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Decimal,
)

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

    def test_returns_float_not_int(self):
        # the documented return type is float even on the HALF-EVEN tie branch
        # with precision_digits=0 (where the rounding factor is an int).
        for method in ("HALF-UP", "HALF-EVEN", "HALF-DOWN", "UP", "DOWN"):
            r = float_round(2.5, precision_digits=0, rounding_method=method)
            self.assertIsInstance(r, float, method)

    def test_large_magnitude_down_does_not_inflate(self):
        # DOWN must never push an exact integer multiple away from zero.
        self.assertEqual(
            float_round(12000000000000.0, precision_digits=2, rounding_method="DOWN"),
            12000000000000.0,
        )
        self.assertEqual(
            float_round(50000000000000.0, precision_digits=2, rounding_method="DOWN"),
            50000000000000.0,
        )

    def test_large_magnitude_up_does_not_overshoot(self):
        # UP on an exact integer must return it unchanged, not overshoot.
        self.assertEqual(
            float_round(2.0**52, precision_digits=0, rounding_method="UP"), 2.0**52
        )
        self.assertEqual(
            float_round(50000000000000.0, precision_digits=2, rounding_method="UP"),
            50000000000000.0,
        )

    def test_large_magnitude_half_even_tie_is_even(self):
        # an exact representable tie at large magnitude must still go to even.
        self.assertEqual(
            float_round(2**50 + 0.5, precision_digits=0, rounding_method="HALF-EVEN"),
            float(2**50),  # 2**50 is even
        )

    def test_half_even_ties(self):
        self.assertEqual(
            float_round(0.5, precision_digits=0, rounding_method="HALF-EVEN"), 0.0
        )
        self.assertEqual(
            float_round(1.5, precision_digits=0, rounding_method="HALF-EVEN"), 2.0
        )
        self.assertEqual(
            float_round(2.5, precision_digits=0, rounding_method="HALF-EVEN"), 2.0
        )

    def test_half_down_ties_round_toward_zero(self):
        self.assertEqual(
            float_round(2.5, precision_digits=0, rounding_method="HALF-DOWN"), 2.0
        )
        self.assertEqual(
            float_round(-2.5, precision_digits=0, rounding_method="HALF-DOWN"), -2.0
        )
        self.assertEqual(
            float_round(3.5, precision_digits=0, rounding_method="HALF-DOWN"), 3.0
        )

    def test_matches_decimal_over_money_range(self):
        # exhaustive cross-check against Decimal for the range that matters.
        dmeth = {
            "HALF-UP": ROUND_HALF_UP,
            "HALF-EVEN": ROUND_HALF_EVEN,
            "HALF-DOWN": ROUND_HALF_DOWN,
            "UP": ROUND_UP,
            "DOWN": ROUND_DOWN,
        }
        rng = random.Random(20260723)
        for _ in range(20000):
            value = round(rng.uniform(-1e6, 1e6), 6)
            digits = rng.choice([0, 1, 2, 3, 4])
            quantum = Decimal(1).scaleb(-digits)
            for method, dm in dmeth.items():
                got = float_round(
                    value, precision_digits=digits, rounding_method=method
                )
                want = float(Decimal(str(value)).quantize(quantum, rounding=dm))
                self.assertAlmostEqual(
                    got,
                    want,
                    delta=10 ** -(digits + 3),
                    msg=f"{method} value={value} digits={digits}",
                )


if __name__ == "__main__":
    unittest.main()
