import datetime
import unittest
from decimal import Decimal

from odoo.libs.documents.coerce import to_float
from odoo.libs.documents.format import (
    ABSOLUTE,
    PARENS,
    TRAIL,
    from_bool,
    from_date,
    from_datetime,
    from_float,
    from_value,
    group_digits,
)


class TestGroupDigits(unittest.TestCase):
    def test_no_separator_is_the_digits(self):
        self.assertEqual(group_digits("1234567"), "1234567")

    def test_groups_from_the_right(self):
        self.assertEqual(group_digits("1234567", ","), "1,234,567")
        self.assertEqual(group_digits("1234", "."), "1.234")

    def test_shorter_than_a_group_is_untouched(self):
        self.assertEqual(group_digits("12", ","), "12")
        self.assertEqual(group_digits("123", ","), "123")


class TestFromFloat(unittest.TestCase):
    def test_two_places_by_default(self):
        self.assertEqual(from_float(1234.5), "1234.50")

    def test_locale_separators(self):
        self.assertEqual(
            from_float(1234567.89, thousand=".", decimal=","), "1.234.567,89"
        )

    def test_half_up_not_bankers(self):
        # Python's own round() and Decimal's default answer 2.67 here.
        self.assertEqual(from_float(2.675), "2.68")
        self.assertEqual(from_float(0.125, places=2), "0.13")

    def test_float_repr_does_not_leak(self):
        self.assertEqual(from_float(0.1 + 0.2), "0.30")

    def test_sign_styles(self):
        self.assertEqual(from_float(-5), "-5.00")
        self.assertEqual(from_float(-5, sign=PARENS), "(5.00)")
        self.assertEqual(from_float(-5, sign=TRAIL), "5.00-")
        self.assertEqual(from_float(-5, sign=ABSOLUTE), "5.00")

    def test_implied_point_for_a_bank_file(self):
        self.assertEqual(from_float(1234.56, implied_point=True, places=2), "123456")
        self.assertEqual(from_float(0.05, implied_point=True), "005")

    def test_zero_places_drops_the_point(self):
        self.assertEqual(from_float(1234.56, places=0), "1235")

    def test_symbol(self):
        self.assertEqual(from_float(9.5, symbol="$"), "$9.50")

    def test_accepts_decimal_and_int(self):
        self.assertEqual(from_float(Decimal("1.005")), "1.01")
        self.assertEqual(from_float(7), "7.00")

    def test_refuses_what_is_not_a_number(self):
        with self.assertRaises(ValueError):
            from_float("not a number")
        with self.assertRaises(ValueError):
            from_float(float("nan"))
        with self.assertRaises(ValueError):
            from_float(float("inf"))

    def test_refuses_an_unknown_sign_style(self):
        with self.assertRaises(ValueError):
            from_float(1, sign="trailing-d")


class TestRoundTrip(unittest.TestCase):
    def test_what_format_writes_coerce_reads(self):
        for value in (0.0, 1.5, -1234.56, 1234567.89, -0.01):
            for thousand, decimal in ((",", "."), (".", ","), ("", ".")):
                written = from_float(value, thousand=thousand, decimal=decimal)
                self.assertAlmostEqual(
                    to_float(written, thousand=thousand or " ", decimal=decimal),
                    round(value, 2),
                    places=2,
                    msg=f"{value!r} via {written!r}",
                )

    def test_accountants_parentheses_survive_the_round_trip(self):
        written = from_float(-1234.56, thousand=",", decimal=".", sign=PARENS)
        self.assertEqual(written, "(1,234.56)")
        self.assertAlmostEqual(to_float(written, thousand=","), -1234.56, places=2)


class TestFromDate(unittest.TestCase):
    def test_iso_by_default(self):
        self.assertEqual(from_date(datetime.date(2026, 8, 29)), "2026-08-29")

    def test_a_format_is_honoured(self):
        self.assertEqual(
            from_date(datetime.date(2026, 8, 29), "%d/%m/%Y"), "29/08/2026"
        )

    def test_a_datetime_narrows_to_its_date(self):
        moment = datetime.datetime(2026, 8, 29, 13, 45)
        self.assertEqual(from_date(moment), "2026-08-29")

    def test_an_iso_string_is_accepted(self):
        self.assertEqual(from_date("2026-08-29"), "2026-08-29")

    def test_refuses_what_is_not_a_date(self):
        with self.assertRaises(ValueError):
            from_date("the 29th")


class TestFromDatetime(unittest.TestCase):
    def test_iso_by_default(self):
        moment = datetime.datetime(2026, 8, 29, 13, 45, 7)
        self.assertEqual(from_datetime(moment), "2026-08-29 13:45:07")

    def test_refuses_a_bare_date(self):
        with self.assertRaises(ValueError):
            from_datetime("not a moment")


class TestFromValue(unittest.TestCase):
    def test_none_is_empty(self):
        self.assertEqual(from_value(None), "")

    def test_a_bool_is_not_a_number(self):
        self.assertEqual(from_value(True), "1")
        self.assertEqual(from_value(False), "0")
        self.assertEqual(from_value(True, true="Y", false="N"), "Y")

    def test_dates_before_numbers(self):
        self.assertEqual(from_value(datetime.date(2026, 8, 29)), "2026-08-29")

    def test_numbers(self):
        self.assertEqual(from_value(3), "3.00")
        self.assertEqual(from_value(3, places=0), "3")

    def test_anything_else_is_its_string(self):
        self.assertEqual(from_value("Café"), "Café")


class TestFromBool(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(from_bool(1), "1")
        self.assertEqual(from_bool(""), "0")
