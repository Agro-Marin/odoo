"""Date-only calendar logic has to read the user's calendar, not UTC's.

Kept out of `test_event_recurrence.py` and `test_calendar.py`: both predate the
fork's ruff-format hook, and touching either rewrites well over a thousand
unrelated lines.

Every case here freezes UTC at 23:30 and puts the user in Pacific/Kiritimati
(UTC+14), where it is already the next day. That is the whole point: a date-only
comparison against `fields.Date.today()` answers for UTC, and the user is asking
about their own today.
"""

from freezegun import freeze_time

from odoo import fields
from odoo.tests import common

# 2026-04-01 23:30 UTC is 2026-04-02 13:30 in Kiritimati.
FROZEN_UTC = "2026-04-01 23:30:00"
USER_TZ = "Pacific/Kiritimati"
UTC_TODAY = "2026-04-01"


@freeze_time(FROZEN_UTC)
class TestUserLocalDates(common.TransactionCase):
    def setUp(self):
        super().setUp()
        self.env.user.tz = USER_TZ

    def test_the_frozen_clock_really_does_straddle_midnight(self):
        # Guards the other three: if this stops holding, they would pass for
        # the wrong reason rather than fail.
        self.assertEqual(str(fields.Date.today()), UTC_TODAY)
        self.assertEqual(
            str(fields.Date.context_today(self.env["calendar.event"])), "2026-04-02"
        )

    def test_allday_event_is_over_once_the_user_day_has_ended(self):
        event = self.env["calendar.event"].create(
            {
                "name": "All day, ending on UTC's today",
                "allday": True,
                "start_date": UTC_TODAY,
                "stop_date": UTC_TODAY,
            }
        )
        # For the user it is already 2026-04-02, so a meeting that ended on
        # 2026-04-01 is behind them. Against UTC's today the comparison is
        # `04-01 < 04-01`, which reports the meeting as still running.
        self.assertTrue(
            event._is_event_over(),
            "an all-day event that ended yesterday in the user's timezone is over",
        )

    def test_recurrence_is_over_once_the_user_day_has_ended(self):
        event = self.env["calendar.event"].create(
            {
                "name": "Recurring all day",
                "allday": True,
                "start_date": UTC_TODAY,
                "stop_date": UTC_TODAY,
                "recurrency": True,
                "rrule_type": "daily",
                "end_type": "count",
                "count": 1,
            }
        )
        self.assertTrue(
            event.recurrence_id._is_event_over(),
            "a recurrence whose every event ended yesterday for the user is over",
        )

    def test_start_date_default_follows_the_user_day(self):
        # `_get_start_date` already converts into `event_tz` when there is a
        # start; only the no-start fallback answered for UTC. `start` is
        # required and defaulted, so the fallback is reachable only on an
        # in-memory record whose start has been cleared -- which is exactly
        # what a form does between opening and picking a time.
        event = self.env["calendar.event"].new({"name": "No start yet", "start": False})
        self.assertFalse(event.start)
        self.assertEqual(str(event._get_start_date()), "2026-04-02")
