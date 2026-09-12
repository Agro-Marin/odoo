from datetime import datetime

from odoo.tests.common import TransactionCase


class TestRecurrenceRule(TransactionCase):
    def test_daily_count(self):
        recurrence = self.env["calendar.recurrence"].create(
            {
                "repeat_unit": "day",
                "repeat_interval": 2,
                "repeat_number": 3,
                "event_tz": "UTC",
            }
        )
        self.assertEqual(recurrence.name, "Every 2 Days for 3 events")

    def test_daily_until(self):
        recurrence = self.env["calendar.recurrence"].create(
            {
                "repeat_unit": "day",
                "repeat_interval": 2,
                "repeat_type": "until",
                "repeat_until": datetime(2024, 11, 15),
                "event_tz": "UTC",
            }
        )
        self.assertEqual(recurrence.name, "Every 2 Days until 2024-11-15")

    def test_daily_none(self):
        recurrence = self.env["calendar.recurrence"].create(
            {
                "repeat_unit": "day",
                "repeat_interval": 2,
                "repeat_type": "",
                "event_tz": "UTC",
            }
        )
        self.assertEqual(recurrence.name, "Every 2 Days")

    def test_weekly_count(self):
        """Every week, on Tuesdays, for 3 occurences"""
        recurrence = self.env["calendar.recurrence"].create(
            {
                "repeat_unit": "week",
                "tue": True,
                "wed": True,
                "repeat_interval": 2,
                "repeat_number": 3,
                "event_tz": "UTC",
            }
        )
        self.assertEqual(
            recurrence.name, "Every 2 Weeks on Tuesday, Wednesday for 3 events"
        )

    def test_weekly_until(self):
        """Every week, on Tuesdays, for 3 occurences"""
        recurrence = self.env["calendar.recurrence"].create(
            {
                "repeat_unit": "week",
                "tue": True,
                "wed": True,
                "repeat_interval": 2,
                "repeat_type": "until",
                "repeat_until": datetime(2024, 11, 15),
                "event_tz": "UTC",
            }
        )
        self.assertEqual(
            recurrence.name, "Every 2 Weeks on Tuesday, Wednesday until 2024-11-15"
        )

    def test_weekly_none(self):
        """Every week, on Tuesdays, for 3 occurences"""
        recurrence = self.env["calendar.recurrence"].create(
            {
                "repeat_unit": "week",
                "tue": True,
                "wed": True,
                "repeat_interval": 2,
                "repeat_type": "",
                "event_tz": "UTC",
            }
        )
        self.assertEqual(recurrence.name, "Every 2 Weeks on Tuesday, Wednesday")

    def test_monthly_count_by_day(self):
        recurrence = self.env["calendar.recurrence"].create(
            {
                "repeat_unit": "month",
                "repeat_interval": 2,
                "month_by": "day",
                "byday": "1",
                "weekday": "MON",
                "repeat_type": "count",
                "repeat_number": 3,
                "event_tz": "UTC",
            }
        )
        self.assertEqual(
            recurrence.name, "Every 2 Months on the First Monday for 3 events"
        )

    def test_monthly_until_by_day(self):
        recurrence = self.env["calendar.recurrence"].create(
            {
                "repeat_unit": "month",
                "repeat_interval": 2,
                "month_by": "day",
                "byday": "1",
                "weekday": "MON",
                "repeat_type": "until",
                "repeat_until": datetime(2024, 11, 15),
                "event_tz": "UTC",
            }
        )
        self.assertEqual(
            recurrence.name, "Every 2 Months on the First Monday until 2024-11-15"
        )

    def test_monthly_none_by_day(self):
        recurrence = self.env["calendar.recurrence"].create(
            {
                "repeat_unit": "month",
                "repeat_interval": 2,
                "month_by": "day",
                "byday": "1",
                "weekday": "MON",
                "repeat_type": "",
                "event_tz": "UTC",
            }
        )
        self.assertEqual(recurrence.name, "Every 2 Months on the First Monday")

    def test_monthly_count_by_date(self):
        recurrence = self.env["calendar.recurrence"].create(
            {
                "repeat_unit": "month",
                "repeat_interval": 2,
                "month_by": "date",
                "day": 27,
                "weekday": "MON",
                "repeat_type": "count",
                "repeat_number": 3,
                "event_tz": "UTC",
            }
        )
        self.assertEqual(recurrence.name, "Every 2 Months day 27 for 3 events")

    def test_monthly_until_by_date(self):
        recurrence = self.env["calendar.recurrence"].create(
            {
                "repeat_unit": "month",
                "repeat_interval": 2,
                "month_by": "date",
                "day": 27,
                "weekday": "MON",
                "repeat_type": "until",
                "repeat_until": datetime(2024, 11, 15),
                "event_tz": "UTC",
            }
        )
        self.assertEqual(recurrence.name, "Every 2 Months day 27 until 2024-11-15")

    def test_monthly_none_by_date(self):
        recurrence = self.env["calendar.recurrence"].create(
            {
                "repeat_unit": "month",
                "repeat_interval": 2,
                "month_by": "date",
                "day": 27,
                "weekday": "MON",
                "repeat_type": "",
                "event_tz": "UTC",
            }
        )
        self.assertEqual(recurrence.name, "Every 2 Months day 27")

    def test_yearly_count(self):
        recurrence = self.env["calendar.recurrence"].create(
            {
                "repeat_unit": "year",
                "repeat_interval": 2,
                "repeat_number": 3,
                "event_tz": "UTC",
            }
        )
        self.assertEqual(recurrence.name, "Every 2 Years for 3 events")

    def test_yearly_until(self):
        recurrence = self.env["calendar.recurrence"].create(
            {
                "repeat_unit": "year",
                "repeat_interval": 2,
                "repeat_type": "until",
                "repeat_until": datetime(2024, 11, 15),
                "event_tz": "UTC",
            }
        )
        self.assertEqual(recurrence.name, "Every 2 Years until 2024-11-15")

    def test_yearly_none(self):
        recurrence = self.env["calendar.recurrence"].create(
            {
                "repeat_unit": "year",
                "repeat_interval": 2,
                "repeat_type": "",
                "event_tz": "UTC",
            }
        )
        self.assertEqual(recurrence.name, "Every 2 Years")
