from odoo.tests import common


class TestRecurrentEvent(common.TransactionCase):
    def setUp(self):
        super().setUp()

        self.CalendarEvent = self.env["calendar.event"]

    def test_recurrent_meeting1(self):
        # In order to test recurrent meetings in Odoo, I create meetings with different recurrence using different test cases.
        # I create a recurrent meeting with daily recurrence and fixed amount of time.
        self.CalendarEvent.create(
            {
                "count": 5,
                "start": "2011-04-13 11:04:00",
                "stop": "2011-04-13 12:04:00",
                "duration": 1.0,
                "name": "Test Meeting",
                "recurrency": True,
                "rrule_type": "daily",
            }
        )
        # I search for all the recurrent meetings
        meetings_count = self.CalendarEvent.with_context(
            {"virtual_id": True}
        ).search_count([("start", ">=", "2011-03-13"), ("stop", "<=", "2011-05-13")])
        self.assertEqual(meetings_count, 5, "Recurrent daily meetings are not created!")

    def test_recurrent_meeting2(self):
        # I create a weekly meeting till a particular end date.
        self.CalendarEvent.create(
            {
                "start": "2011-04-18 11:47:00",
                "stop": "2011-04-18 12:47:00",
                "day": 1,
                "duration": 1.0,
                "until": "2011-04-30",
                "end_type": "end_date",
                "fri": True,
                "mon": True,
                "thu": True,
                "tue": True,
                "wed": True,
                "name": "Review code with programmer",
                "recurrency": True,
                "rrule_type": "weekly",
            }
        )

        # I search for all the recurrent weekly meetings.
        meetings_count = self.CalendarEvent.search_count(
            [("start", ">=", "2011-03-13"), ("stop", "<=", "2011-05-13")]
        )
        self.assertEqual(
            meetings_count, 10, "Recurrent weekly meetings are not created!"
        )

    def test_recurrent_meeting_forever_is_capped_in_years(self):
        # A `forever` recurrence has to be bounded by a horizon in YEARS, not by
        # a fixed number of occurrences. `MAX_RECURRENT_EVENT` caps the
        # enumeration at 720 events whatever the frequency, so a yearly forever
        # event used to materialise 720 rows -- 720 years of meetings -- and a
        # monthly one 60 years. Daily and weekly stay on the occurrence cap
        # because 720 of either already falls inside the horizon (~2 and ~14
        # years), which is why they are asserted unchanged here.
        values = {
            "duration": 1.0,
            "end_type": "forever",
            "start": "2026-04-01 05:00:00",
            "stop": "2026-04-01 06:00:00",
            "recurrency": True,
        }
        for rrule_type, name, expected_count in (
            ("daily", "Daily Meeting", 720),
            ("monthly", "Monthly Meeting", 180),
            ("yearly", "Yearly Meeting", 15),
        ):
            with self.subTest(rrule_type=rrule_type):
                self.CalendarEvent.create(
                    dict(values, name=name, rrule_type=rrule_type)
                )
                meetings_count = self.CalendarEvent.search_count([("name", "=", name)])
                self.assertEqual(
                    meetings_count,
                    expected_count,
                    f"A forever {rrule_type} recurrence should stop at {expected_count} events",
                )

        # The horizon is configurable. `set_param`/`get_param_int` is the pair
        # this fork exposes on `ir.config_parameter`; there is no `set_int`.
        self.env["ir.config_parameter"].sudo().set_param(
            "calendar.max_recurrence_years", 5
        )
        for rrule_type, name, expected_count in (
            ("daily", "Custom Daily Meeting", 720),
            ("monthly", "Custom Monthly Meeting", 60),
            ("yearly", "Custom Yearly Meeting", 5),
        ):
            with self.subTest(rrule_type=rrule_type, max_recurrence_years=5):
                self.CalendarEvent.create(
                    dict(values, name=name, rrule_type=rrule_type)
                )
                meetings_count = self.CalendarEvent.search_count([("name", "=", name)])
                self.assertEqual(
                    meetings_count,
                    expected_count,
                    f"A forever {rrule_type} recurrence should follow calendar.max_recurrence_years",
                )
