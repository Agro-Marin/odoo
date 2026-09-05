import unittest
from datetime import date, datetime

from odoo.tools.date_utils import _TRUNCATE_UNIT, _apply_unit_term


class TestSetUnitTerm(unittest.TestCase):
    def test_every_truncate_unit_is_one_relativedelta_accepts(self):
        from dateutil.relativedelta import relativedelta

        for unit in _TRUNCATE_UNIT:
            relativedelta(dt1=None, dt2=None, **{unit: 1})

    def test_setting_a_day_of_month(self):
        self.assertEqual(
            _apply_unit_term(date(2026, 8, 29), "=", "=15d"), date(2026, 8, 15)
        )

    def test_setting_an_hour_truncates_below_it(self):
        self.assertEqual(
            _apply_unit_term(datetime(2026, 8, 29, 13, 47, 12), "=", "=5H"),
            datetime(2026, 8, 29, 5, 0, 0),
        )

    def test_setting_a_week_is_refused_by_name(self):
        with self.assertRaises(ValueError) as caught:
            _apply_unit_term(date(2026, 8, 29), "=", "=3w")
        self.assertIn("'w'", str(caught.exception))

    def test_adding_weeks_still_works(self):
        self.assertEqual(
            _apply_unit_term(date(2026, 8, 29), "+", "+2w"), date(2026, 9, 12)
        )
