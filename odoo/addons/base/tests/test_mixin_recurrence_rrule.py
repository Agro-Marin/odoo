from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from dateutil import rrule

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestRecurrenceWeekStart(TransactionCase):
    def test_a_user_without_a_language_still_gets_a_real_week_start(self):
        user = new_test_user(self.env, login="rrule_no_lang")
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE res_partner SET lang = NULL WHERE id = %s", [user.partner_id.id]
        )
        self.env.invalidate_all()
        self.assertFalse(user.lang)

        week_start = (
            self.env["mixin.recurrence.rrule"].with_user(user)._get_lang_week_start()
        )

        self.assertIn(week_start.weekday, range(7))

    def test_repeating_until_no_date_is_refused_as_a_user_error(self):
        rule = self.env["mixin.recurrence.rrule"].new(
            {
                "repeat_interval": 1,
                "repeat_unit": "day",
                "repeat_type": "until",
                "repeat_until": False,
            }
        )
        with self.assertRaises(UserError):
            rule._rrule_serialize()


@tagged("post_install", "-at_install")
class TestRecurrenceRruleOccurrences(TransactionCase):
    def _local_dates(self, recurrence, start, tz):
        return [
            occurrence.replace(tzinfo=UTC).astimezone(ZoneInfo(tz)).date()
            for occurrence, _stop in sorted(
                recurrence._range_calculation(start, timedelta(hours=1))
            )
        ]

    def test_an_east_of_utc_bimonthly_rule_starts_on_its_first_local_date(self):
        recurrence = self.env["mixin.recurrence.rrule"].new(
            {
                "event_tz": "Asia/Tokyo",
                "repeat_unit": "month",
                "repeat_interval": 2,
                "month_by": "date",
                "day": 1,
                "repeat_type": "count",
                "repeat_number": 3,
            }
        )
        self.assertEqual(
            self._local_dates(recurrence, datetime(2026, 9, 30, 20, 0), "Asia/Tokyo"),
            [date(2026, 10, 1), date(2026, 12, 1), date(2027, 2, 1)],
        )

    def test_an_east_of_utc_biweekly_rule_starts_on_its_first_local_date(self):
        Rrule = self.env["mixin.recurrence.rrule"]
        recurrence = Rrule.new(
            {
                "event_tz": "Asia/Tokyo",
                "repeat_unit": "week",
                "repeat_interval": 2,
                "sun": True,
                "repeat_type": "count",
                "repeat_number": 3,
            }
        )
        with patch.object(type(Rrule), "_get_lang_week_start", return_value=rrule.SU):
            local_dates = self._local_dates(
                recurrence, datetime(2026, 10, 3, 16, 0), "Asia/Tokyo"
            )
        self.assertEqual(
            local_dates, [date(2026, 10, 4), date(2026, 10, 18), date(2026, 11, 1)]
        )

    def test_a_utc_until_is_read_as_the_recurrence_local_date(self):
        values = self.env["mixin.recurrence.rrule"]._rrule_parse(
            "FREQ=WEEKLY;UNTIL=20200120T055959Z;BYDAY=MO",
            datetime(2020, 1, 6, 16, 0),
            ZoneInfo("America/Mexico_City"),
        )
        self.assertEqual(values["repeat_until"], date(2020, 1, 19))
        self.assertEqual(values["repeat_type"], "until")

    def test_a_monthly_setpos_rule_stays_the_nth_weekday_of_the_month(self):
        values = self.env["mixin.recurrence.rrule"]._rrule_parse(
            "FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1;COUNT=3", datetime(2020, 1, 6, 16, 0)
        )
        self.assertEqual(values["repeat_unit"], "month")
        self.assertEqual(values["month_by"], "day")
        self.assertEqual(values["weekday"], "MON")
        self.assertEqual(values["byday"], "1")
        self.assertNotIn("mon", values)

    def test_a_yearly_rule_stays_yearly(self):
        Rrule = self.env["mixin.recurrence.rrule"]
        for rule in (
            "FREQ=YEARLY",
            "FREQ=YEARLY;BYMONTH=4;BYDAY=2SU",
            "FREQ=YEARLY;BYDAY=2SU",
        ):
            with self.subTest(rule=rule):
                values = Rrule._rrule_parse(rule, datetime(2020, 3, 8, 16, 0))
                self.assertEqual(values["repeat_unit"], "year")
                self.assertEqual(values["month_by"], "date")
                self.assertNotIn("weekday", values)


@tagged("post_install", "-at_install")
class TestRecurrenceRruleMonthEdges(TransactionCase):
    def _rule(self, **values):
        return self.env["mixin.recurrence.rrule"].new(
            {"repeat_interval": 1, "repeat_type": "count", **values}
        )

    def _dates(self, recurrence, start):
        return [
            occurrence.date()
            for occurrence, _stop in sorted(
                recurrence._range_calculation(start, timedelta(hours=1))
            )
        ]

    def test_the_last_day_of_the_month_is_parsed(self):
        values = self.env["mixin.recurrence.rrule"]._rrule_parse(
            "FREQ=MONTHLY;COUNT=12;BYMONTHDAY=-1", datetime(2024, 1, 31, 16, 0)
        )
        self.assertEqual(values["repeat_unit"], "month")
        self.assertEqual(values["month_by"], "date")
        self.assertEqual(values["day"], -1)

    def test_the_last_day_of_the_month_is_serialised(self):
        recurrence = self._rule(
            repeat_unit="month", month_by="date", day=-1, repeat_number=12
        )
        self.assertEqual(
            recurrence._rrule_serialize(), "FREQ=MONTHLY;COUNT=12;BYMONTHDAY=-1"
        )

    def test_the_last_day_of_the_month_falls_on_each_month_end(self):
        recurrence = self._rule(
            event_tz="UTC",
            repeat_unit="month",
            month_by="date",
            day=-1,
            repeat_number=13,
        )
        self.assertEqual(
            self._dates(recurrence, datetime(2024, 1, 31, 16, 0)),
            [
                date(2024, 1, 31),
                date(2024, 2, 29),
                date(2024, 3, 31),
                date(2024, 4, 30),
                date(2024, 5, 31),
                date(2024, 6, 30),
                date(2024, 7, 31),
                date(2024, 8, 31),
                date(2024, 9, 30),
                date(2024, 10, 31),
                date(2024, 11, 30),
                date(2024, 12, 31),
                date(2025, 1, 31),
            ],
        )

    def test_the_last_day_of_the_month_is_named(self):
        recurrence = self._rule(
            repeat_unit="month", month_by="date", day=-1, repeat_number=12
        )
        self.assertEqual(
            recurrence.get_recurrence_name(),
            "Every 1 Months on the last day for 12 events",
        )

    def test_a_yearly_nth_weekday_is_parsed_in_its_start_month(self):
        values = self.env["mixin.recurrence.rrule"]._rrule_parse(
            "FREQ=YEARLY;COUNT=3;BYMONTH=3;BYDAY=2SU", datetime(2024, 3, 10, 16, 0)
        )
        self.assertEqual(values["repeat_unit"], "year")
        self.assertEqual(values["month_by"], "day")
        self.assertEqual(values["weekday"], "SUN")
        self.assertEqual(values["byday"], "2")

    def test_a_yearly_nth_weekday_month_is_the_local_start_month(self):
        values = self.env["mixin.recurrence.rrule"]._rrule_parse(
            "FREQ=YEARLY;BYMONTH=3;BYDAY=1SU",
            datetime(2024, 2, 29, 20, 0),
            ZoneInfo("Asia/Tokyo"),
        )
        self.assertEqual(values["month_by"], "day")
        self.assertEqual(values["weekday"], "SUN")
        self.assertEqual(values["byday"], "1")

    def test_a_yearly_nth_weekday_is_serialised_with_its_month(self):
        recurrence = self._rule(
            repeat_unit="year",
            month_by="day",
            weekday="SUN",
            byday="2",
            repeat_number=3,
        )
        self.assertEqual(
            recurrence._rrule_value(
                str(recurrence._get_rrule(dtstart=datetime(2024, 3, 10), bounded=False))
            ),
            "FREQ=YEARLY;COUNT=3;BYMONTH=3;BYDAY=+2SU",
        )
        values = recurrence._rrule_parse(
            "FREQ=YEARLY;COUNT=3;BYMONTH=3;BYDAY=+2SU", datetime(2024, 3, 10, 16, 0)
        )
        self.assertEqual(
            (values["month_by"], values["weekday"], values["byday"]),
            ("day", "SUN", "2"),
        )

    def test_a_yearly_nth_weekday_repeats_on_that_weekday(self):
        recurrence = self._rule(
            event_tz="UTC",
            repeat_unit="year",
            month_by="day",
            weekday="SUN",
            byday="2",
            repeat_number=3,
        )
        self.assertEqual(
            self._dates(recurrence, datetime(2024, 3, 10, 16, 0)),
            [date(2024, 3, 10), date(2025, 3, 9), date(2026, 3, 8)],
        )

    def test_a_yearly_rule_on_its_start_date_ignores_the_weekday(self):
        recurrence = self._rule(
            event_tz="UTC",
            repeat_unit="year",
            month_by="date",
            weekday="SUN",
            byday="2",
            repeat_number=3,
        )
        self.assertEqual(
            self._dates(recurrence, datetime(2024, 3, 10, 16, 0)),
            [date(2024, 3, 10), date(2025, 3, 10), date(2026, 3, 10)],
        )
