"""Regression tests for ``start_of`` / ``end_of`` tzinfo handling."""

import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from odoo.libs.datetime.date_utils import end_of, start_of

TZ = ZoneInfo("America/Mexico_City")
GRANULARITIES = ("year", "quarter", "month", "week", "day", "hour")


class TestStartEndOf(unittest.TestCase):
    def test_aware_datetime_keeps_tzinfo(self):
        aware = datetime(2026, 5, 15, 14, 30, tzinfo=TZ)
        for granularity in GRANULARITIES:
            self.assertIs(start_of(aware, granularity).tzinfo, TZ, granularity)
            self.assertIs(end_of(aware, granularity).tzinfo, TZ, granularity)

    def test_naive_datetime_stays_naive(self):
        naive = datetime(2026, 5, 15, 14, 30)
        for granularity in GRANULARITIES:
            self.assertIsNone(start_of(naive, granularity).tzinfo, granularity)
            self.assertIsNone(end_of(naive, granularity).tzinfo, granularity)

    def test_date_input_unaffected(self):
        d = date(2026, 5, 15)
        self.assertEqual(start_of(d, "month"), date(2026, 5, 1))
        self.assertEqual(end_of(d, "month"), date(2026, 5, 31))

    def test_boundaries_are_correct(self):
        aware = datetime(2026, 5, 15, 14, 30, tzinfo=TZ)
        self.assertEqual(
            start_of(aware, "day"), datetime(2026, 5, 15, 0, 0, tzinfo=TZ)
        )
        self.assertEqual(
            end_of(aware, "day"),
            datetime(2026, 5, 15, 23, 59, 59, 999999, tzinfo=TZ),
        )


if __name__ == "__main__":
    unittest.main()
