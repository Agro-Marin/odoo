from odoo.tests import common

from odoo.addons.calendar.models.calendar_recurrence import MAX_RECURRENT_EVENT


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

    def test_forever_recurrence_stops_at_a_horizon_of_years(self):
        """A ``forever`` recurrence is bounded in years, not in occurrences.

        Capping every ``forever`` recurrence at ``MAX_RECURRENT_EVENT``
        occurrences bounds the row count and nothing else: how far into the
        future those rows reach depends entirely on the frequency. A yearly
        meeting materialises 720 events, i.e. 720 *years* of them, and a
        monthly one 60 years -- all of them real rows, each with its attendees
        and its push to the connected calendars.

        The horizon is ``calendar.max_recurrence_years``, 15 by default.
        Daily and weekly are left on the occurrence cap: 720 of either already
        falls inside the horizon.
        """
        values = {
            "duration": 1.0,
            "end_type": "forever",
            "start": "2026-04-01 05:00:00",
            "stop": "2026-04-01 06:00:00",
            "recurrency": True,
        }
        for rrule_type, name, expected in (
            ("daily", "Daily Meeting", MAX_RECURRENT_EVENT),
            ("monthly", "Monthly Meeting", 15 * 12),
            ("yearly", "Yearly Meeting", 15),
        ):
            with self.subTest(rrule_type=rrule_type):
                self.CalendarEvent.create(
                    dict(values, name=name, rrule_type=rrule_type)
                )
                self.assertEqual(
                    self.CalendarEvent.search_count([("name", "=", name)]),
                    expected,
                    f"A forever {rrule_type} recurrence must stop at {expected} events.",
                )

        # The horizon is a system parameter, so a calendar that genuinely needs
        # to reach further can say so.
        self.env["ir.config_parameter"].sudo().set_param(
            "calendar.max_recurrence_years", 5
        )
        for rrule_type, name, expected in (
            ("daily", "Custom Daily Meeting", MAX_RECURRENT_EVENT),
            ("monthly", "Custom Monthly Meeting", 5 * 12),
            ("yearly", "Custom Yearly Meeting", 5),
        ):
            with self.subTest(rrule_type=rrule_type):
                self.CalendarEvent.create(
                    dict(values, name=name, rrule_type=rrule_type)
                )
                self.assertEqual(
                    self.CalendarEvent.search_count([("name", "=", name)]),
                    expected,
                    f"A forever {rrule_type} recurrence must honour the parameter.",
                )

    def test_forever_recurrence_still_serialises_without_a_count(self):
        """The horizon bounds enumeration only, never the canonical rule string.

        ``_get_rrule(bounded=False)`` is what ``_rrule_serialize`` feeds to the
        .ics attachment and to the connected calendars, and it must keep
        carrying no ``COUNT``: a ``COUNT`` there re-reads as
        ``end_type='count'`` and turns an open-ended series into a finite one.
        This is the half upstream has no equivalent of -- it caps the string
        too -- so it is the half most likely to break when the cap is added.
        """
        event = self.CalendarEvent.create(
            {
                "duration": 1.0,
                "end_type": "forever",
                "start": "2026-04-01 05:00:00",
                "stop": "2026-04-01 06:00:00",
                "recurrency": True,
                "rrule_type": "yearly",
                "name": "Serialised Yearly Meeting",
            }
        )
        recurrence = event.recurrence_id
        self.assertNotIn("COUNT", recurrence.rrule)
        parsed = recurrence._rrule_parse(recurrence.rrule, event.start)
        self.assertEqual(parsed["end_type"], "forever")
