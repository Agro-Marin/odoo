from math import log10

from odoo.tests.common import TransactionCase
from odoo.tools import (
    float_compare,
    float_is_zero,
    float_repr,
    float_round,
    float_split,
    float_split_str,
)


class TestFloatPrecision(TransactionCase):
    def test_rounding_02(self):
        currency = self.env.ref("base.EUR")

        def try_round(amount, expected, digits=2, method="HALF-UP"):
            value = float_round(amount, precision_digits=digits, rounding_method=method)
            result = float_repr(value, precision_digits=digits)
            self.assertEqual(
                result,
                expected,
                "Rounding error: got %s, expected %s" % (result, expected),
            )

        try_round(2.674, "2.67")
        try_round(2.675, "2.68")
        try_round(-2.675, "-2.68")
        try_round(0.001, "0.00")
        try_round(-0.001, "0.00")
        try_round(0.0049, "0.00")
        try_round(0.005, "0.01")
        try_round(-0.005, "-0.01")
        try_round(6.6 * 0.175, "1.16")
        try_round(-6.6 * 0.175, "-1.16")
        try_round(5.015, "5.02", method="HALF-EVEN")
        try_round(5.025, "5.02", method="HALF-EVEN")
        try_round(-5.015, "-5.02", method="HALF-EVEN")
        try_round(-5.025, "-5.02", method="HALF-EVEN")

        def try_zero(amount, expected):
            self.assertEqual(
                currency.is_zero(amount),
                expected,
                "Rounding error: %s should be zero!" % amount,
            )

        try_zero(0.01, False)
        try_zero(-0.01, False)
        try_zero(0.001, True)
        try_zero(-0.001, True)
        try_zero(0.0046, True)
        try_zero(-0.0046, True)
        try_zero(2.68 - 2.675, False)
        try_zero(2.68 - 2.676, True)
        try_zero(2.676 - 2.68, True)
        try_zero(2.675 - 2.68, False)

        def try_compare(amount1, amount2, expected):
            self.assertEqual(
                currency.compare_amounts(amount1, amount2),
                expected,
                "Rounding error, compare_amounts(%s,%s) should be %s"
                % (amount1, amount2, expected),
            )

        try_compare(0.001, 0.001, 0)
        try_compare(-0.001, -0.001, 0)
        try_compare(0.001, 0.002, 0)
        try_compare(-0.001, -0.002, 0)
        try_compare(2.675, 2.68, 0)
        try_compare(2.676, 2.68, 0)
        try_compare(-2.676, -2.68, 0)
        try_compare(2.674, 2.68, -1)
        try_compare(-2.674, -2.68, 1)
        try_compare(3, 2.68, 1)
        try_compare(-3, -2.68, -1)
        try_compare(0.01, 0, 1)
        try_compare(-0.01, 0, -1)

    def test_rounding_03(self):

        def try_round(amount, expected, digits=3, method="HALF-UP"):
            value = float_round(amount, precision_digits=digits, rounding_method=method)
            result = float_repr(value, precision_digits=digits)
            self.assertEqual(
                result,
                expected,
                "Rounding error: got %s, expected %s" % (result, expected),
            )

        try_round(2.6735, "2.674")
        try_round(-2.6735, "-2.674")
        try_round(2.6745, "2.675")
        try_round(-2.6745, "-2.675")
        try_round(2.6744, "2.674")
        try_round(-2.6744, "-2.674")
        try_round(0.0004, "0.000")
        try_round(-0.0004, "0.000")
        try_round(357.4555, "357.456")
        try_round(-357.4555, "-357.456")
        try_round(457.4554, "457.455")
        try_round(-457.4554, "-457.455")

        try_round(2.6735, "2.673", method="HALF-DOWN")
        try_round(-2.6735, "-2.673", method="HALF-DOWN")
        try_round(2.6745, "2.674", method="HALF-DOWN")
        try_round(-2.6745, "-2.674", method="HALF-DOWN")
        try_round(2.6744, "2.674", method="HALF-DOWN")
        try_round(-2.6744, "-2.674", method="HALF-DOWN")
        try_round(0.0004, "0.000", method="HALF-DOWN")
        try_round(-0.0004, "0.000", method="HALF-DOWN")
        try_round(357.4555, "357.455", method="HALF-DOWN")
        try_round(-357.4555, "-357.455", method="HALF-DOWN")
        try_round(457.4554, "457.455", method="HALF-DOWN")
        try_round(-457.4554, "-457.455", method="HALF-DOWN")

        try_round(2.6735, "2.674", method="HALF-EVEN")
        try_round(-2.6735, "-2.674", method="HALF-EVEN")
        try_round(2.6745, "2.674", method="HALF-EVEN")
        try_round(-2.6745, "-2.674", method="HALF-EVEN")
        try_round(2.6744, "2.674", method="HALF-EVEN")
        try_round(-2.6744, "-2.674", method="HALF-EVEN")
        try_round(0.0004, "0.000", method="HALF-EVEN")
        try_round(-0.0004, "0.000", method="HALF-EVEN")
        try_round(357.4555, "357.456", method="HALF-EVEN")
        try_round(-357.4555, "-357.456", method="HALF-EVEN")
        try_round(457.4554, "457.455", method="HALF-EVEN")
        try_round(-457.4554, "-457.455", method="HALF-EVEN")

        try_round(8.175, "8.175", method="UP")
        try_round(8.1751, "8.176", method="UP")
        try_round(-8.175, "-8.175", method="UP")
        try_round(-8.1751, "-8.176", method="UP")
        try_round(-6.000, "-6.000", method="UP")
        try_round(1.8, "2", 0, method="UP")
        try_round(-1.8, "-2", 0, method="UP")

        try_round(2.425, "2.425", method="DOWN")
        try_round(2.4249, "2.424", method="DOWN")
        try_round(-2.425, "-2.425", method="DOWN")
        try_round(-2.4249, "-2.424", method="DOWN")
        try_round(-2.500, "-2.500", method="DOWN")
        try_round(1.8, "1", 0, method="DOWN")
        try_round(-1.8, "-1", 0, method="DOWN")

        fractions = [
            0.0,
            0.015,
            0.01499,
            0.675,
            0.67499,
            0.4555,
            0.4555,
            0.45555,
        ]
        expecteds = [".00", ".02", ".01", ".68", ".67", ".46", ".456", ".4556"]
        precisions = [2, 2, 2, 2, 2, 2, 3, 4]
        for magnitude in range(7):
            for frac, exp, prec in zip(fractions, expecteds, precisions, strict=False):
                for sign in [-1, 1]:
                    for x in range(0, 10000, 97):
                        n = x * 10**magnitude
                        f = sign * (n + frac)
                        f_exp = ("-" if f != 0 and sign == -1 else "") + str(n) + exp
                        try_round(f, f_exp, digits=prec)

        def try_zero(amount, expected):
            self.assertEqual(
                float_is_zero(amount, precision_digits=3),
                expected,
                "Rounding error: %s should be zero!" % amount,
            )

        try_zero(0.0002, True)
        try_zero(-0.0002, True)
        try_zero(0.00034, True)
        try_zero(0.0005, False)
        try_zero(-0.0005, False)
        try_zero(0.0008, False)
        try_zero(-0.0008, False)

        def try_compare(amount1, amount2, expected):
            self.assertEqual(
                float_compare(amount1, amount2, precision_digits=3),
                expected,
                "Rounding error, compare_amounts(%s,%s) should be %s"
                % (amount1, amount2, expected),
            )

        try_compare(0.0003, 0.0004, 0)
        try_compare(-0.0003, -0.0004, 0)
        try_compare(0.0002, 0.0005, -1)
        try_compare(-0.0002, -0.0005, 1)
        try_compare(0.0009, 0.0004, 1)
        try_compare(-0.0009, -0.0004, -1)
        try_compare(557.4555, 557.4556, 0)
        try_compare(-557.4555, -557.4556, 0)
        try_compare(657.4444, 657.445, -1)
        try_compare(-657.4444, -657.445, 1)

        def try_round(amount, expected, precision_rounding=None, method="HALF-UP"):
            value = float_round(
                amount,
                precision_rounding=precision_rounding,
                rounding_method=method,
            )
            result = float_repr(value, precision_digits=2)
            self.assertEqual(
                result,
                expected,
                "Rounding error: got %s, expected %s" % (result, expected),
            )

        try_round(-457.4554, "-457.45", precision_rounding=0.05)
        try_round(457.444, "457.50", precision_rounding=0.5)
        try_round(457.3, "455.00", precision_rounding=5)
        try_round(457.5, "460.00", precision_rounding=5)
        try_round(457.1, "456.00", precision_rounding=3)
        try_round(2.5, "2.50", precision_rounding=0.05, method="DOWN")
        try_round(-2.5, "-2.50", precision_rounding=0.05, method="DOWN")

    def test_rounding_04(self):
        currency = self.env.ref("base.EUR")
        currency_rate = self.env["res.currency.rate"]

        def try_roundtrip(value, expected, date):
            rate = currency_rate.create(
                {"name": date, "rate": value, "currency_id": currency.id}
            )
            self.assertEqual(
                rate.rate,
                expected,
                "Roundtrip error: got %s back from db, expected %s" % (rate, expected),
            )

        try_roundtrip(10000.999999, 10000.999999, "2000-01-03")

    def test_rounding_large_magnitude(self):
        rescued_145 = {"HALF-UP": "0.15", "HALF-DOWN": "0.14", "HALF-EVEN": "0.14"}
        for method in ("HALF-UP", "HALF-DOWN", "HALF-EVEN"):
            for value in (5.6e12, 1e13, 1.23456789e14, 1e15):
                self.assertEqual(
                    float_round(value, precision_rounding=0.01, rounding_method=method),
                    value,
                    "spurious digit at 2-digit precision for %s (%s)" % (value, method),
                )
                self.assertEqual(
                    float_round(value, precision_digits=0, rounding_method=method),
                    value,
                    "spurious unit at 0-digit precision for %s (%s)" % (value, method),
                )
            self.assertEqual(
                float_round(-1e13, precision_rounding=0.01, rounding_method=method),
                -1e13,
                "spurious digit for negative large value (%s)" % method,
            )
            self.assertEqual(
                float_repr(
                    float_round(0.145, precision_digits=2, rounding_method=method),
                    precision_digits=2,
                ),
                rescued_145[method],
                "representation-error tie no longer rescued (%s)" % method,
            )
        self.assertEqual(float_round(1.005, precision_digits=2), 1.01)
        self.assertEqual(float_round(2.675, precision_digits=2), 2.68)
        self.assertEqual(
            float_round(1e13 + 0.5, precision_rounding=1.0, rounding_method="HALF-UP"),
            1e13 + 1,
        )

    def test_float_split_05(self):
        currency = self.env.ref("base.EUR")

        def try_split(value, expected, split_fun, rounding=None):
            digits = (
                max(0, -int(log10(currency.rounding))) if rounding is None else rounding
            )
            result = split_fun(value, precision_digits=digits)
            self.assertEqual(
                result,
                expected,
                "Split error: got %s, expected %s" % (result, expected),
            )

        try_split(2.674, ("2", "67"), float_split_str)
        try_split(2.675, ("2", "68"), float_split_str)
        try_split(-2.675, ("-2", "68"), float_split_str)
        try_split(0.001, ("0", "00"), float_split_str)
        try_split(-0.001, ("0", "00"), float_split_str)
        try_split(42, ("42", "00"), float_split_str)
        try_split(0.1, ("0", "10"), float_split_str)
        try_split(13.0, ("13", ""), float_split_str, rounding=0)

        try_split(2.674, (2, 67), float_split)
        try_split(2.675, (2, 68), float_split)
        try_split(-2.675, (-2, 68), float_split)
        try_split(0.001, (0, 0), float_split)
        try_split(-0.001, (0, 0), float_split)
        try_split(42, (42, 0), float_split)
        try_split(0.1, (0, 10), float_split)
        try_split(13.0, (13, 0), float_split, rounding=0)

    def test_rounding_invalid(self):
        with self.assertRaises(ValueError):
            float_is_zero(0.01, precision_digits=3, precision_rounding=0.01)

        with self.assertRaises(ValueError):
            float_is_zero(0.0, precision_rounding=0.0)

        with self.assertRaises(ValueError):
            float_is_zero(0.0, precision_rounding=-0.1)

        with self.assertRaises(ValueError):
            float_compare(0.01, 0.02, precision_digits=3, precision_rounding=0.01)

        with self.assertRaises(ValueError):
            float_compare(1.0, 1.0, precision_rounding=0.0)

        with self.assertRaises(ValueError):
            float_compare(1.0, 1.0, precision_rounding=-0.1)

        with self.assertRaises(ValueError):
            float_round(0.01, precision_digits=3, precision_rounding=0.01)

        with self.assertRaises(ValueError):
            float_round(-1.0, precision_digits=0, precision_rounding=0.1)

        with self.assertRaises(ValueError):
            float_round(1.25, precision_rounding=0.0)

        with self.assertRaises(ValueError):
            float_round(1.25, precision_rounding=-0.1)

        with self.assertRaises(ValueError):
            float_round(1.25, precision_digits=-1)

        with self.assertRaises(ValueError):
            float_round(1.25, precision_digits=0.5)

    def test_amount_to_text_10(self):
        currency = self.env.ref("base.EUR")

        amount_target = currency.amount_to_text(0.29)
        amount_test = currency.amount_to_text(0.28)
        self.assertNotEqual(
            amount_test,
            amount_target,
            "Amount in text should not depend on float representation",
        )
