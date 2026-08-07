import unittest
from datetime import date

import babel

from odoo.libs.datetime.date_utils import weeknumber


class TestWeeknumber(unittest.TestCase):
    def test_explicit_monday_override_honored(self):
        en_us = babel.Locale.parse("en_US")
        fr_fr = babel.Locale.parse("fr_FR")
        d = date(2026, 1, 4)
        self.assertEqual(weeknumber(en_us, d, first_week_day=0), (2026, 1))
        self.assertEqual(weeknumber(en_us, d, first_week_day=0), weeknumber(fr_fr, d))

    def test_default_uses_locale(self):
        en_us = babel.Locale.parse("en_US")
        self.assertEqual(weeknumber(en_us, date(2026, 1, 4)), (2026, 2))


if __name__ == "__main__":
    unittest.main()
