import datetime
import unittest

from odoo.libs.documents.coerce import (
    infer_separators,
    normalize_number,
    strip_currency_symbol,
    to_date,
    to_datetime,
    to_float,
)

SYMBOLS = frozenset({"$", "€", "£", "MXN"})


class TestInferSeparators(unittest.TestCase):
    def test_two_separators_name_themselves(self):
        self.assertEqual(infer_separators("1.234.567,89"), (".", ","))
        self.assertEqual(infer_separators("1,234,567.89"), (",", "."))

    def test_one_separator_is_ambiguous_so_the_caller_decides(self):
        self.assertEqual(infer_separators("1.234"), (" ", "."))
        self.assertEqual(
            infer_separators("1.234", thousand=".", decimal=","), (".", ",")
        )

    def test_a_currency_symbol_is_not_a_separator(self):
        self.assertEqual(infer_separators("€1.234,56"), (".", ","))

    def test_accountants_parentheses_are_not_separators(self):
        self.assertEqual(infer_separators("(1,234.56)"), (",", "."))


class TestStripCurrencySymbol(unittest.TestCase):
    def test_plain_number(self):
        self.assertEqual(strip_currency_symbol("1234.56", SYMBOLS), "1234.56")

    def test_leading_and_trailing_symbols(self):
        self.assertEqual(strip_currency_symbol("$ 1234.56", SYMBOLS), "1234.56")
        self.assertEqual(strip_currency_symbol("1234.56 €", SYMBOLS), "1234.56")

    def test_parentheses_are_a_negative(self):
        self.assertEqual(strip_currency_symbol("(1234.56)", SYMBOLS), "-1234.56")
        self.assertEqual(strip_currency_symbol("($ 1234.56)", SYMBOLS), "-1234.56")

    def test_an_unknown_symbol_is_not_a_number(self):
        self.assertIsNone(strip_currency_symbol("1234.56 zł", SYMBOLS))

    def test_without_a_table_any_currency_character_counts(self):
        self.assertEqual(strip_currency_symbol("1234.56 ₹"), "1234.56")
        self.assertIsNone(strip_currency_symbol("1234.56 kg"))

    def test_not_a_number_at_all(self):
        self.assertIsNone(strip_currency_symbol("hello", SYMBOLS))


class TestNormalizeNumber(unittest.TestCase):
    def test_european_grouping(self):
        self.assertEqual(
            normalize_number("1.234.567,89", symbols=SYMBOLS), "1234567.89"
        )

    def test_anglo_grouping(self):
        self.assertEqual(
            normalize_number("1,234,567.89", symbols=SYMBOLS), "1234567.89"
        )

    def test_a_space_before_the_symbol_defeats_inference(self):
        # Preserved from base_import exactly: the space counts as a third
        # non-numeric character, so the two real separators are no longer
        # distinguishable and the caller's defaults stand. `to_float` is the
        # API that copes; this one is what the import path has always done.
        self.assertEqual(normalize_number("$ 1,234.56", symbols=SYMBOLS), "1,234.56")

    def test_currency_and_grouping_without_a_space(self):
        self.assertEqual(normalize_number("$1,234.56", symbols=SYMBOLS), "1234.56")

    def test_scientific_notation_is_expanded(self):
        self.assertEqual(float(normalize_number("1.5e3", symbols=SYMBOLS)), 1500.0)

    def test_not_a_number(self):
        self.assertIsNone(normalize_number("n/a", symbols=SYMBOLS))


class TestToFloat(unittest.TestCase):
    def test_the_shape_a_generative_extractor_returns(self):
        # The prompt asks models to copy numbers exactly as printed; this is
        # what "exactly as printed" looks like on an invoice.
        self.assertEqual(to_float("$1,234.56"), 1234.56)
        self.assertEqual(to_float("1.234,56 €"), 1234.56)
        self.assertEqual(to_float("(421.35)"), -421.35)

    def test_numbers_pass_through(self):
        self.assertEqual(to_float(12), 12.0)
        self.assertEqual(to_float(12.5), 12.5)

    def test_a_boolean_is_not_a_total(self):
        with self.assertRaises(ValueError):
            to_float(True)

    def test_one_separator_stays_ambiguous_and_raises(self):
        # `1,200` is twelve hundred in London and one-point-two in Madrid, and
        # on a total the wrong reading is out by 1000x. Two separators
        # disambiguate each other; one does not, and guessing is refused for
        # the same reason an ambiguous date is.
        with self.assertRaises(ValueError):
            to_float("1,200")
        self.assertEqual(to_float("1,200", thousand=",", decimal="."), 1200.0)

    def test_not_a_number_raises(self):
        with self.assertRaises(ValueError):
            to_float("see attached")


class TestToDate(unittest.TestCase):
    def test_iso_is_always_accepted(self):
        self.assertEqual(to_date("2026-03-12"), datetime.date(2026, 3, 12))

    def test_iso_datetime_is_truncated(self):
        self.assertEqual(to_date("2026-03-12T09:30:00"), datetime.date(2026, 3, 12))

    def test_dates_pass_through(self):
        self.assertEqual(
            to_date(datetime.date(2026, 3, 12)), datetime.date(2026, 3, 12)
        )
        self.assertEqual(
            to_date(datetime.datetime(2026, 3, 12, 9, 30)), datetime.date(2026, 3, 12)
        )

    def test_a_declared_format_is_tried_first(self):
        self.assertEqual(
            to_date("12/03/2026", ("%d/%m/%Y",)), datetime.date(2026, 3, 12)
        )
        self.assertEqual(
            to_date("12/03/2026", ("%m/%d/%Y",)), datetime.date(2026, 12, 3)
        )

    def test_an_ambiguous_date_is_never_guessed(self):
        with self.assertRaises(ValueError):
            to_date("12/03/2026")

    def test_nonsense_raises(self):
        with self.assertRaises(ValueError):
            to_date("last Tuesday")


class TestToDatetime(unittest.TestCase):
    def test_iso(self):
        self.assertEqual(
            to_datetime("2026-03-12 09:30:00"), datetime.datetime(2026, 3, 12, 9, 30)
        )

    def test_a_declared_format(self):
        self.assertEqual(
            to_datetime("12/03/2026 09:30", ("%d/%m/%Y %H:%M",)),
            datetime.datetime(2026, 3, 12, 9, 30),
        )

    def test_nonsense_raises(self):
        with self.assertRaises(ValueError):
            to_datetime("soon")
