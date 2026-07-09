"""Regression tests for ``odoo.libs.datetime.date_utils.weeknumber``.

The ``first_week_day`` override accepts ``0`` (Monday).  The guard must
distinguish "not provided" (``None``) from the falsy-but-valid ``0``; otherwise
callers asking for a Monday-based week (e.g. resource weekly-hours) silently get
the locale default instead.
"""

import unittest
from datetime import date

import babel

from odoo.libs.datetime.date_utils import weeknumber


class TestWeeknumber(unittest.TestCase):
    def test_explicit_monday_override_honored(self):
        # en_US starts weeks on Sunday; asking explicitly for Monday (0) must
        # match a genuine Monday-start locale, not fall back to the en_US default.
        en_us = babel.Locale.parse("en_US")
        fr_fr = babel.Locale.parse("fr_FR")  # Monday-start locale
        d = date(2026, 1, 4)
        self.assertEqual(weeknumber(en_us, d, first_week_day=0), (2026, 1))
        self.assertEqual(weeknumber(en_us, d, first_week_day=0), weeknumber(fr_fr, d))

    def test_default_uses_locale(self):
        en_us = babel.Locale.parse("en_US")
        self.assertEqual(weeknumber(en_us, date(2026, 1, 4)), (2026, 2))


if __name__ == "__main__":
    unittest.main()
