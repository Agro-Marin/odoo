import unittest
from decimal import Decimal

from odoo.libs.numbers.float_utils import _INVERTDICT, float_invert


def _decimal_intent(value: float) -> float:
    """The reciprocal of the shortest decimal that round-trips to *value*."""
    return float(1 / Decimal(repr(value)))


class TestFloatInvertRecoversDecimalIntent(unittest.TestCase):
    """``float_invert`` inverts the decimal the caller wrote, not its float.

    The two differ.  ``1 / 1e-5`` is 99999.99999999999 -- correctly rounded, and
    not what any caller of a rounding factor means.  A test asserting binary
    exactness would therefore pass on the wrong answer, so every assertion here
    is against the decimal.
    """

    def test_one_over_ten_to_the_minus_eleven(self):
        # The %.15e reconstruction this replaced renders 1e-11 as
        # 9.999999999999999e-12 -- a coefficient that no longer round-trips --
        # and returned 100000000000.00002.
        self.assertEqual(float_invert(1e-11), 1e11)

    def test_decimal_factors_all_recover_their_intent(self):
        wrong = [
            (value, float_invert(value), _decimal_intent(value))
            for digits in range(26)
            for coefficient in (1, 2, 5)
            if (value := float(f"{coefficient}e-{digits}"))
            and float_invert(value) != _decimal_intent(value)
        ]
        self.assertEqual(wrong, [])

    def test_plain_division_would_not_pass_the_above(self):
        # Guards the test itself: if 1/x were good enough, the assertion above
        # would prove nothing about the implementation.
        self.assertNotEqual(1 / 1e-5, _decimal_intent(1e-5))

    def test_table_is_a_fast_path_not_a_correction(self):
        # Every entry must agree with the general path; a table entry that
        # disagrees is a second implementation, and would drift.
        disagreeing = {
            value: (tabled, _decimal_intent(value))
            for value, tabled in _INVERTDICT.items()
            if tabled != _decimal_intent(value)
        }
        self.assertEqual(disagreeing, {})

    def test_non_decimal_values_still_invert(self):
        self.assertEqual(float_invert(0.25), 4.0)
        self.assertEqual(float_invert(0.125), 8.0)
        self.assertEqual(float_invert(2.0), 0.5)

    def test_negative_values_keep_their_sign(self):
        self.assertEqual(float_invert(-0.01), -100.0)
        self.assertEqual(float_invert(-0.25), -4.0)

    def test_zero_raises_a_named_error(self):
        with self.assertRaises(ZeroDivisionError):
            float_invert(0.0)


if __name__ == "__main__":
    unittest.main()
