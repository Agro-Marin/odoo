from datetime import datetime, timedelta

from odoo.tests import TransactionCase


class TestCalendarStopOnCreate(TransactionCase):
    def test_stop_follows_start_and_duration(self):
        event = self.env["calendar.event"].create(
            {"name": "Meeting", "start": datetime(2026, 9, 1, 10, 0), "duration": 3.0}
        )

        self.assertEqual(event.stop, datetime(2026, 9, 1, 13, 0))

    def test_an_explicit_stop_wins(self):
        event = self.env["calendar.event"].create(
            {
                "name": "Meeting",
                "start": datetime(2026, 9, 1, 10, 0),
                "stop": datetime(2026, 9, 1, 11, 30),
            }
        )

        self.assertEqual(event.stop, datetime(2026, 9, 1, 11, 30))
        self.assertEqual(event.duration, 1.5)

    def test_start_alone_takes_the_default_duration(self):
        hours = self.env["calendar.event"].get_default_duration()

        event = self.env["calendar.event"].create(
            {"name": "Meeting", "start": datetime(2026, 9, 1, 10, 0)}
        )

        self.assertEqual(
            event.stop, datetime(2026, 9, 1, 10, 0) + timedelta(hours=hours)
        )
