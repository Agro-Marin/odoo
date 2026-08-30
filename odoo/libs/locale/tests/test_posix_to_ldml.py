import datetime
import unittest

from babel import Locale
from babel.dates import format_datetime

from odoo.libs.locale.conversions import posix_to_ldml

EN = Locale.parse("en_US")


class TestPosixToLdml(unittest.TestCase):
    def test_basic_pattern(self):
        self.assertEqual(posix_to_ldml("%Y-%m-%d", EN), "yyyy-MM-dd")

    def test_space_padded_day(self):
        self.assertEqual(posix_to_ldml("%e/%m/%Y", EN), "d/MM/yyyy")

    def test_unknown_directive_raises_value_error(self):
        with self.assertRaises(ValueError) as cm:
            posix_to_ldml("%q/%Y", EN)
        self.assertIn("%q", str(cm.exception))


class TestPosixToLdmlLiteralApostrophe(unittest.TestCase):
    """A literal apostrophe belongs inside the quoted run, not between two runs.

    It is not `isalpha()`, so it used to fall through to the plain append and
    land between a closing and an opening quote. LDML then read the result as a
    literal "o" plus an escaped apostrophe, followed by `clock` as pattern
    letters -- babel rendered "%d o'clock" as "29 o'7lo715".
    """

    WHEN = datetime.datetime(2026, 8, 29, 15, 4, 5)

    CASES = [
        "%d o'clock",
        "%d 'de' %m",
        "%H'%M",
        "%d/%m/%Y",
        "%H:%M:%S",
        "%d %B %Y",
        "%I:%M %p",
        "%a %d %b %Y",
        "%d %m %Y at %H %M",
        "'",
        "''",
        "a'b'c",
        "%d'",
        "'%d",
    ]

    def test_babel_agrees_with_strftime(self):
        for fmt in self.CASES:
            with self.subTest(fmt=fmt):
                pattern = posix_to_ldml(fmt, EN)
                self.assertEqual(
                    format_datetime(self.WHEN, pattern, locale=EN),
                    self.WHEN.strftime(fmt),
                )

    def test_the_patterns_themselves(self):
        self.assertEqual(posix_to_ldml("%d o'clock", EN), "dd 'o''clock'")

    def test_a_run_of_only_apostrophes_is_not_wrapped(self):
        # LDML reads a leading "''" as one escaped apostrophe rather than as an
        # opening quote, so wrapping this run would render two apostrophes.
        self.assertEqual(posix_to_ldml("%H'%M", EN), "HH''mm")
        self.assertEqual(format_datetime(self.WHEN, "HH''mm", locale=EN), "15'04")


if __name__ == "__main__":
    unittest.main()
