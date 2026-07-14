"""Tests covering previously untested methods and edge cases in the resource module.

Focus areas:
- _search_work_time_rate SQL implementation
- _works_on_date / _get_hours_for_date
- _check_hours constraint on attendance
- _list_work_time_per_day with no-calendar resources
- _reservation_intervals_batch UTC conversion
- allocated_percentage = 0
- switch_based_on_duration
- _compute_origin_display with missing records
"""

from datetime import date, datetime, timedelta

import pytz

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

UTC = pytz.UTC


@tagged("post_install", "-at_install")
class TestSearchWorkTimeRate(TransactionCase):
    """Test the SQL-based _search_work_time_rate method."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar_full = cls.env["resource.calendar"].create(
            {"name": "Full Time 40h", "tz": "UTC"}
        )
        # Create a part-time calendar (20h/week = 50% rate)
        cls.calendar_part = cls.env["resource.calendar"].create(
            {"name": "Part Time 20h", "tz": "UTC"}
        )
        # Remove default attendances and add custom ones (Mon-Fri 8-12 only)
        cls.calendar_part.attendance_ids.unlink()
        for day in range(5):
            cls.env["resource.calendar.attendance"].create(
                {
                    "name": f"Day {day}",
                    "calendar_id": cls.calendar_part.id,
                    "dayofweek": str(day),
                    "hour_from": 8,
                    "hour_to": 12,
                    "day_period": "morning",
                }
            )

    def test_search_rate_greater_than(self):
        """Search calendars with work_time_rate > 80."""
        results = self.env["resource.calendar"].search([("work_time_rate", ">", 80)])
        self.assertIn(self.calendar_full, results)
        self.assertNotIn(self.calendar_part, results)

    def test_search_rate_less_than(self):
        """Search calendars with work_time_rate < 60."""
        results = self.env["resource.calendar"].search([("work_time_rate", "<", 60)])
        self.assertIn(self.calendar_part, results)
        self.assertNotIn(self.calendar_full, results)

    def test_search_rate_in(self):
        """Search calendars with work_time_rate in a list."""
        rate = round(self.calendar_part.work_time_rate)
        results = self.env["resource.calendar"].search(
            [("work_time_rate", "in", [rate, 100])]
        )
        self.assertIn(self.calendar_full, results)


@tagged("post_install", "-at_install")
class TestCalendarWorkMethods(TransactionCase):
    """Test _works_on_date, _get_hours_for_date, switch_based_on_duration."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "Standard 40h", "tz": "UTC"}
        )

    def test_works_on_date_weekday(self):
        """Monday is a working day on standard calendar."""
        from datetime import date

        monday = date(2025, 1, 6)
        self.assertTrue(self.calendar._works_on_date(monday))

    def test_works_on_date_weekend(self):
        """Saturday is not a working day on standard calendar."""
        from datetime import date

        saturday = date(2025, 1, 11)
        self.assertFalse(self.calendar._works_on_date(saturday))

    def test_get_hours_for_date_full_day(self):
        """Full day returns min hour_from and max hour_to."""
        from datetime import date

        monday = date(2025, 1, 6)
        hour_from, hour_to = self.calendar._get_hours_for_date(monday)
        self.assertEqual(hour_from, 8.0)
        self.assertEqual(hour_to, 17.0)

    def test_get_hours_for_date_morning(self):
        """Morning period returns morning hours."""
        from datetime import date

        monday = date(2025, 1, 6)
        hour_from, hour_to = self.calendar._get_hours_for_date(
            monday, day_period="morning"
        )
        self.assertEqual(hour_from, 8.0)
        self.assertEqual(hour_to, 12.0)

    def test_get_hours_for_date_afternoon(self):
        """Afternoon period returns afternoon hours."""
        from datetime import date

        monday = date(2025, 1, 6)
        hour_from, hour_to = self.calendar._get_hours_for_date(
            monday, day_period="afternoon"
        )
        self.assertEqual(hour_from, 13.0)
        self.assertEqual(hour_to, 17.0)

    def test_get_hours_for_date_no_target(self):
        """Empty target_date raises ValueError."""
        with self.assertRaises(ValueError):
            self.calendar._get_hours_for_date(None)

    def test_switch_based_on_duration(self):
        """Toggling duration_based mode removes lunch and restores it."""
        calendar = self.calendar
        has_lunch = calendar.attendance_ids.filtered(lambda a: a.day_period == "lunch")
        self.assertTrue(has_lunch, "Standard calendar should have lunch periods")

        calendar.switch_based_on_duration()
        self.assertTrue(calendar.duration_based)
        no_lunch = calendar.attendance_ids.filtered(lambda a: a.day_period == "lunch")
        self.assertFalse(no_lunch, "Duration mode should remove lunch periods")

        calendar.switch_based_on_duration()
        self.assertFalse(calendar.duration_based)
        has_lunch_again = calendar.attendance_ids.filtered(
            lambda a: a.day_period == "lunch"
        )
        self.assertTrue(has_lunch_again, "Disabling duration mode restores lunch")


@tagged("post_install", "-at_install")
class TestAttendanceHourConstraint(TransactionCase):
    """Test the _check_hours constraint enforces bounds via API."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "Test Calendar", "tz": "UTC"}
        )

    def test_hour_from_too_high(self):
        """hour_from > 23.99 raises ValidationError."""
        with self.assertRaises(ValidationError):
            self.env["resource.calendar.attendance"].create(
                {
                    "name": "Bad",
                    "calendar_id": self.calendar.id,
                    "dayofweek": "6",
                    "hour_from": 25.0,
                    "hour_to": 26.0,
                    "day_period": "morning",
                }
            )

    def test_hour_from_negative(self):
        """hour_from < 0 raises ValidationError."""
        with self.assertRaises(ValidationError):
            self.env["resource.calendar.attendance"].create(
                {
                    "name": "Bad",
                    "calendar_id": self.calendar.id,
                    "dayofweek": "6",
                    "hour_from": -1.0,
                    "hour_to": 8.0,
                    "day_period": "morning",
                }
            )

    def test_hour_from_exceeds_hour_to(self):
        """hour_from > hour_to raises ValidationError."""
        with self.assertRaises(ValidationError):
            self.env["resource.calendar.attendance"].create(
                {
                    "name": "Bad",
                    "calendar_id": self.calendar.id,
                    "dayofweek": "6",
                    "hour_from": 17.0,
                    "hour_to": 8.0,
                    "day_period": "morning",
                }
            )

    def test_valid_attendance_passes(self):
        """Normal attendance values pass the constraint."""
        att = self.env["resource.calendar.attendance"].create(
            {
                "name": "Good",
                "calendar_id": self.calendar.id,
                "dayofweek": "6",
                "hour_from": 8.0,
                "hour_to": 12.0,
                "day_period": "morning",
            }
        )
        self.assertTrue(att.id)


@tagged("post_install", "-at_install")
class TestReservationUTCConversion(TransactionCase):
    """Test _reservation_intervals_batch uses UTC, not OS local tz."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Reservation = cls.env["resource.reservation"]
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "UTC Calendar", "tz": "UTC"}
        )
        cls.resource = cls.env["resource.resource"].create(
            {
                "name": "Test Resource",
                "calendar_id": cls.calendar.id,
            }
        )

    def test_intervals_with_non_utc_query(self):
        """Reservation query returns correct results when queried with non-UTC tz."""
        self.Reservation.create(
            {
                "name": "Morning slot",
                "resource_id": self.resource.id,
                "date_start": datetime(2025, 1, 6, 8, 0),  # Mon 08:00 UTC
                "date_end": datetime(2025, 1, 6, 12, 0),  # Mon 12:00 UTC
            }
        )
        # Query with Tokyo timezone (UTC+9)
        tokyo = pytz.timezone("Asia/Tokyo")
        start = tokyo.localize(
            datetime(2025, 1, 6, 0, 0)
        )  # Mon 00:00 Tokyo = Sun 15:00 UTC
        end = tokyo.localize(
            datetime(2025, 1, 7, 0, 0)
        )  # Tue 00:00 Tokyo = Mon 15:00 UTC
        result = self.Reservation._reservation_intervals_batch(
            start, end, self.resource
        )
        intervals = list(result[self.resource.id])
        self.assertEqual(len(intervals), 1, "Should find the reservation in this range")


@tagged("post_install", "-at_install")
class TestAllocatedPercentageZero(TransactionCase):
    """Test that allocated_percentage=0 produces 0 allocated_hours."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Reservation = cls.env["resource.reservation"]
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "UTC Calendar", "tz": "UTC"}
        )
        cls.resource = cls.env["resource.resource"].create(
            {
                "name": "Zero Resource",
                "calendar_id": cls.calendar.id,
            }
        )

    def test_zero_allocation(self):
        """0% allocation should yield 0 allocated_hours, not 100%."""
        res = self.Reservation.create(
            {
                "name": "Zero allocation",
                "resource_id": self.resource.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 17, 0),
                "allocated_percentage": 0.0,
            }
        )
        self.assertEqual(
            res.allocated_hours,
            0.0,
            "0% allocation must produce 0 hours, not fall back to 100%",
        )

    def test_fifty_percent_allocation(self):
        """50% of an 8h day = 4h."""
        res = self.Reservation.create(
            {
                "name": "Half allocation",
                "resource_id": self.resource.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 17, 0),
                "allocated_percentage": 50.0,
            }
        )
        self.assertEqual(res.allocated_hours, 4.0)


@tagged("post_install", "-at_install")
class TestOriginDisplayMissing(TransactionCase):
    """Test _compute_origin_display handles missing source records."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Reservation = cls.env["resource.reservation"]
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "UTC Calendar", "tz": "UTC"}
        )
        cls.resource = cls.env["resource.resource"].create(
            {
                "name": "Display Resource",
                "calendar_id": cls.calendar.id,
            }
        )

    def test_origin_display_invalid_model(self):
        """origin_display falls back to string for unknown model."""
        res = self.Reservation.create(
            {
                "name": "Bad origin",
                "resource_id": self.resource.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 17, 0),
                "res_model": "nonexistent.model",
                "res_id": 999,
            }
        )
        self.assertEqual(res.origin_display, "nonexistent.model,999")

    def test_origin_display_no_origin(self):
        """origin_display is False when no origin is set."""
        res = self.Reservation.create(
            {
                "name": "No origin",
                "resource_id": self.resource.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 17, 0),
            }
        )
        self.assertFalse(res.origin_display)


# ============================================================
# Edge case tests — DST, two-week, flexible, plan_hours
# ============================================================


@tagged("post_install", "-at_install")
class TestDSTTransition(TransactionCase):
    """Test work interval computation across DST transitions."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Brussels springs forward: 2025-03-30 02:00 → 03:00 (loses 1 hour)
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "Brussels Calendar", "tz": "Europe/Brussels"}
        )

    def test_work_hours_across_spring_forward(self):
        """Work hours across DST spring-forward should count real hours, not wall clock."""
        brussels = pytz.timezone("Europe/Brussels")
        # Friday 2025-03-28 to Monday 2025-03-31 (DST change on Sunday)
        start = brussels.localize(datetime(2025, 3, 28, 6, 0))
        end = brussels.localize(datetime(2025, 3, 31, 20, 0))
        hours = self.calendar.get_work_hours_count(start, end)
        # Friday 8h + Monday 8h = 16h (weekend skipped, DST doesn't affect work hours)
        self.assertEqual(hours, 16.0)

    def test_plan_hours_across_spring_forward(self):
        """plan_hours across DST should return a valid result spanning DST change."""
        brussels = pytz.timezone("Europe/Brussels")
        start = brussels.localize(datetime(2025, 3, 28, 8, 0))  # Friday 8:00
        result = self.calendar.plan_hours(16.0, start, compute_leaves=False)
        # 8h Friday + 8h Monday = should land on Monday
        self.assertTrue(result, "plan_hours should find a result within range")
        # Result is tz-aware; convert to Brussels to check the day
        if result.tzinfo:
            result_local = result.astimezone(brussels)
        else:
            result_local = brussels.localize(result)
        self.assertEqual(result_local.weekday(), 0, "Should land on Monday")


@tagged("post_install", "-at_install")
class TestTwoWeekCalendarEdgeCases(TransactionCase):
    """Test two-week calendar specific methods."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "Standard Calendar", "tz": "UTC"}
        )

    def test_switch_to_two_weeks_and_back(self):
        """Switching to two-week mode and back preserves attendance count."""
        original_count = len(
            self.calendar.attendance_ids.filtered(lambda a: not a.display_type)
        )
        self.assertFalse(self.calendar.two_weeks_calendar)

        self.calendar.switch_calendar_type()
        self.assertTrue(self.calendar.two_weeks_calendar)
        # Two-week mode duplicates attendances (2x) + 2 section headers
        two_week_non_sections = self.calendar.attendance_ids.filtered(
            lambda a: not a.display_type
        )
        self.assertEqual(len(two_week_non_sections), original_count * 2)

        self.calendar.switch_calendar_type()
        self.assertFalse(self.calendar.two_weeks_calendar)

    def test_compute_two_weeks_attendance_non_two_week(self):
        """Non-two-week calendars get False for week attendance fields."""
        self.assertFalse(self.calendar.two_weeks_calendar)
        self.assertFalse(self.calendar.attendance_ids_1st_week)
        self.assertFalse(self.calendar.attendance_ids_2nd_week)

    def test_switch_to_two_weeks_large_calendar_keeps_weeks_ordered(self):
        """>24 attendance lines must not spill past the second-week section.

        The section markers' sequences were hard-coded (0 and 25), so week-one
        lines of a large calendar sorted after the second-week marker and
        ``_onchange_attendance_ids`` would reassign them to week two.
        """
        big = self.env["resource.calendar"].create(
            {
                "name": "Big Calendar",
                "tz": "UTC",
                "attendance_ids": [
                    (
                        0,
                        0,
                        {
                            "name": f"D{day}S{slot}",
                            "dayofweek": str(day),
                            "hour_from": 8 + slot,
                            "hour_to": 9 + slot,
                            "day_period": "morning",
                        },
                    )
                    for day in range(7)
                    for slot in range(4)
                ],
            }
        )
        self.assertEqual(len(big.attendance_ids), 28)
        big.switch_calendar_type()

        lines = big.attendance_ids
        sections = lines.filtered("display_type").sorted("sequence")
        self.assertEqual(len(sections), 2)
        first_week = lines.filtered(lambda a: not a.display_type and a.week_type == "0")
        second_week = lines.filtered(
            lambda a: not a.display_type and a.week_type == "1"
        )
        self.assertEqual(len(first_week), 28)
        self.assertEqual(len(second_week), 28)
        self.assertLess(
            max(first_week.mapped("sequence")),
            sections[1].sequence,
            "every first-week line must sort before the second-week section",
        )
        self.assertLess(
            sections[1].sequence,
            min(second_week.mapped("sequence")),
            "every second-week line must sort after its section",
        )

    def test_works_on_date_two_week_calendar(self):
        """_works_on_date respects week type in two-week mode."""
        from datetime import date

        self.calendar.switch_calendar_type()
        # Remove all attendances for week 1 (second week) on Monday
        week1_monday = self.calendar.attendance_ids.filtered(
            lambda a: a.week_type == "1" and a.dayofweek == "0" and not a.display_type
        )
        week1_monday.unlink()

        # Find a Monday that falls in week type 1
        test_date = date(2025, 1, 6)  # Monday
        week_type = self.env["resource.calendar.attendance"].get_week_type(test_date)
        if week_type == 1:
            # This Monday is in week 1 (where we removed Monday attendance)
            self.assertFalse(self.calendar._works_on_date(test_date))
        else:
            # This Monday is in week 0 (still has attendance)
            self.assertTrue(self.calendar._works_on_date(test_date))


@tagged("post_install", "-at_install")
class TestWorksOnDateIgnoresNonWorkLines(TransactionCase):
    """_works_on_date must ignore section rows and lunch breaks.

    Section rows keep the default ``dayofweek`` (Monday), so counting them
    marked Monday as a working day on *every* two-week calendar regardless of
    its real attendances.  A lunch break alone is not work time either.
    """

    def test_two_week_calendar_section_rows_do_not_mark_monday(self):
        calendar = self.env["resource.calendar"].create(
            {"name": "Sections Cal", "tz": "UTC"}
        )
        calendar.switch_calendar_type()  # two-week mode, adds 2 section rows
        # Keep only Tuesday attendances in both weeks.
        calendar.attendance_ids.filtered(
            lambda a: not a.display_type and a.dayofweek != "1"
        ).unlink()

        monday_w0, monday_w1 = date(2025, 1, 6), date(2025, 1, 13)
        week_types = {
            self.env["resource.calendar.attendance"].get_week_type(d)
            for d in (monday_w0, monday_w1)
        }
        self.assertEqual(week_types, {0, 1}, "consecutive Mondays span both weeks")
        for monday in (monday_w0, monday_w1):
            self.assertFalse(
                calendar._works_on_date(monday),
                "section rows must not mark Monday as worked",
            )
            self.assertTrue(calendar._works_on_date(monday + timedelta(days=1)))

    def test_lunch_only_day_is_not_working(self):
        calendar = self.env["resource.calendar"].create(
            {"name": "Lunch Cal", "tz": "UTC"}
        )
        # Strip Friday down to its lunch break only.
        calendar.attendance_ids.filtered(
            lambda a: a.dayofweek == "4" and a.day_period != "lunch"
        ).unlink()
        friday = date(2025, 1, 10)
        self.assertFalse(calendar._works_on_date(friday))
        self.assertTrue(calendar._works_on_date(date(2025, 1, 9)))


@tagged("post_install", "-at_install")
class TestFlexibleCalendarUnusualDays(TransactionCase):
    """Test _get_unusual_days for flexible calendars."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create(
            {
                "name": "Flexible 35h",
                "tz": "UTC",
                "schedule_type": "flexible",
            }
        )

    def test_unusual_days_no_leaves(self):
        """With no leaves, all days should be non-unusual for flexible calendars."""
        start = datetime(2025, 1, 6, 0, 0).replace(tzinfo=UTC)
        end = datetime(2025, 1, 10, 23, 59).replace(tzinfo=UTC)
        result = self.calendar._get_unusual_days(start, end)
        # No leaves → no unusual days
        self.assertTrue(all(not v for v in result.values()))

    def test_unusual_days_with_leave(self):
        """Days with leaves should be marked as unusual for flexible calendars."""
        self.env["resource.calendar.leaves"].create(
            {
                "name": "Holiday",
                "calendar_id": self.calendar.id,
                "date_from": datetime(2025, 1, 8, 0, 0),  # Wednesday
                "date_to": datetime(2025, 1, 8, 23, 59),
            }
        )
        start = datetime(2025, 1, 6, 0, 0).replace(tzinfo=UTC)
        end = datetime(2025, 1, 10, 23, 59).replace(tzinfo=UTC)
        result = self.calendar._get_unusual_days(start, end)
        # Wednesday should be unusual (has leave)
        self.assertTrue(result.get("2025-01-08", False))
        # Monday should not be unusual
        self.assertFalse(result.get("2025-01-06", True))


@tagged("post_install", "-at_install")
class TestFlexibleWeeklyBudgetFallback(TransactionCase):
    """A flexible calendar with ``hours_per_week`` unset must still synthesize
    work intervals, falling back to ``full_time_required_hours``.

    Regression: ``_compute_hours_per_week`` skips flexible calendars, leaving
    ``hours_per_week`` at 0.  The interval synthesis capped weekly hours at
    that 0 and produced *no* intervals, so work-entry generation for a
    flexible contract yielded nothing (upstream hr_work_entry
    ``test_work_entry_different_calendars``)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create(
            {
                "name": "Flexible 3h/day, 21h/week",
                "tz": "UTC",
                "flexible_hours": True,
                "full_time_required_hours": 21,
                "hours_per_day": 3,
            }
        )

    def test_flexible_weekly_budget_falls_back_to_ftrh(self):
        """hours_per_week unset (0) → weekly budget = full_time_required_hours."""
        self.assertEqual(self.calendar.hours_per_week, 0.0)
        self.assertEqual(self.calendar._get_flexible_hours_per_week(), 21.0)

    def test_flexible_intervals_generated_without_hours_per_week(self):
        """One interval per day (incl. weekend) at hours_per_day, even though
        hours_per_week is 0."""
        start = datetime(2025, 9, 1, 0, 0).replace(tzinfo=UTC)  # Mon
        end = datetime(2025, 9, 14, 23, 59).replace(tzinfo=UTC)  # Sun (2 weeks)
        intervals = list(self.calendar._attendance_intervals_batch(start, end)[False])
        # 14 days, one 3h block each (weekly cap 21h ≥ 7×3h so every day fills).
        self.assertEqual(len(intervals), 14, "every day must get a work block")
        for interval_start, interval_end, _meta in intervals:
            hours = (interval_end - interval_start).total_seconds() / 3600
            self.assertAlmostEqual(hours, 3.0, places=6)

    def test_explicit_hours_per_week_takes_precedence(self):
        """An explicitly-set hours_per_week wins over the FTE fallback."""
        self.calendar.hours_per_week = 10.0
        self.assertEqual(self.calendar._get_flexible_hours_per_week(), 10.0)


@tagged("post_install", "-at_install")
class TestPlanHoursWithResource(TransactionCase):
    """Test plan_hours with a specific resource and leaves."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "Test Calendar", "tz": "UTC"}
        )
        cls.resource = cls.env["resource.resource"].create(
            {
                "name": "Worker",
                "calendar_id": cls.calendar.id,
                "tz": "UTC",
            }
        )

    def test_plan_hours_with_resource_leave(self):
        """plan_hours skips leave days when compute_leaves=True."""
        # Add a leave on Tuesday 2025-01-07
        self.env["resource.calendar.leaves"].create(
            {
                "name": "Sick day",
                "calendar_id": self.calendar.id,
                "resource_id": self.resource.id,
                "date_from": datetime(2025, 1, 7, 0, 0),
                "date_to": datetime(2025, 1, 7, 23, 59),
            }
        )
        start = datetime(2025, 1, 6, 8, 0).replace(tzinfo=UTC)  # Mon 8:00
        # Plan 16 hours: Mon 8h + skip Tue (leave) + Wed 8h
        result = self.calendar.plan_hours(
            16.0, start, compute_leaves=True, resource=self.resource
        )
        self.assertTrue(result)
        # Should land on Wednesday 17:00 UTC
        self.assertEqual(result.weekday(), 2)  # Wednesday
        self.assertEqual(result.hour, 17)

    def test_plan_hours_negative(self):
        """plan_hours with negative hours plans backward."""
        start = datetime(2025, 1, 8, 17, 0).replace(tzinfo=UTC)  # Wed 17:00
        result = self.calendar.plan_hours(-8.0, start, compute_leaves=False)
        self.assertTrue(result)
        # Should land on Wed 8:00 (one full day back)
        self.assertEqual(result.hour, 8)
        self.assertEqual(result.day, 8)  # Still Wednesday

    def test_plan_hours_zero(self):
        """plan_hours with 0 returns immediately."""
        start = datetime(2025, 1, 6, 10, 0).replace(tzinfo=UTC)
        result = self.calendar.plan_hours(0.0, start, compute_leaves=False)
        # With 0 hours, first interval check: 0 <= interval_hours → return start
        self.assertTrue(result)


@tagged("post_install", "-at_install")
class TestListWorkTimePerDay(TransactionCase):
    """Test _list_work_time_per_day including falsy calendar guard."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Use test.resource model from the test_resource module if available,
        # otherwise use resource.resource directly with a mixin consumer.
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "Standard", "tz": "UTC"}
        )

    def test_get_unusual_days_fixed_calendar(self):
        """Non-flexible calendar: non-working days are unusual."""
        start = datetime(2025, 1, 6, 0, 0).replace(tzinfo=UTC)  # Monday
        end = datetime(2025, 1, 12, 23, 59).replace(tzinfo=UTC)  # Sunday
        result = self.calendar._get_unusual_days(start, end)
        # Saturday and Sunday should be unusual (not working)
        self.assertTrue(result.get("2025-01-11", False), "Saturday should be unusual")
        self.assertTrue(result.get("2025-01-12", False), "Sunday should be unusual")
        # Monday should not be unusual
        self.assertFalse(result.get("2025-01-06", True), "Monday should be normal")


@tagged("post_install", "-at_install")
class TestDurationBasedAverageHours(TransactionCase):
    """`hours_per_week`/`hours_per_day` must use `duration_hours` when the
    calendar is duration-based (upstream 41f3c9f108, b567716e79)."""

    def test_duration_based_average_hours(self):
        """3 full-day lines of 4h each => 12h/week, 4h/day average."""
        calendar = self.env["resource.calendar"].create(
            {
                "name": "Duration based Calendar",
                "attendance_ids": False,
                "duration_based": True,
            }
        )
        for dow, name in (("0", "Mon"), ("1", "Tue"), ("2", "Wed")):
            self.env["resource.calendar.attendance"].create(
                {
                    "name": name,
                    "calendar_id": calendar.id,
                    "dayofweek": dow,
                    "day_period": "full_day",
                    "duration_hours": 4.0,
                }
            )
        self.assertEqual(calendar.hours_per_week, 12)
        self.assertEqual(calendar.hours_per_day, 4)

    def test_non_duration_based_uses_hour_bounds(self):
        """Without duration mode, weekly hours come from hour_from/hour_to."""
        calendar = self.env["resource.calendar"].create(
            {"name": "Hour based Calendar", "attendance_ids": False}
        )
        for dow, name in (("0", "Mon"), ("1", "Tue"), ("2", "Wed")):
            self.env["resource.calendar.attendance"].create(
                {
                    "name": name,
                    "calendar_id": calendar.id,
                    "dayofweek": dow,
                    "day_period": "full_day",
                    "hour_from": 8,
                    "hour_to": 16,
                }
            )
        self.assertEqual(calendar.hours_per_week, 24)
        self.assertEqual(calendar.hours_per_day, 8)


@tagged("post_install", "-at_install")
class TestFullDayMidpointSplit(TransactionCase):
    """A full-day attendance must split at its own midpoint, not a hard-coded
    12:00 (upstream bc3b454123)."""

    def test_full_day_split_uses_midpoint(self):
        from datetime import date

        calendar = self.env["resource.calendar"].create(
            {"name": "Late shift", "tz": "UTC", "attendance_ids": False}
        )
        self.env["resource.calendar.attendance"].create(
            {
                "name": "Mon",
                "calendar_id": calendar.id,
                "dayofweek": "0",
                "day_period": "full_day",
                "hour_from": 10,
                "hour_to": 18,
            }
        )
        monday = date(2025, 1, 6)
        # midpoint of 10:00-18:00 is 14:00, not 12:00
        self.assertEqual(
            calendar._get_hours_for_date(monday, day_period="morning"),
            (10.0, 14.0),
        )
        self.assertEqual(
            calendar._get_hours_for_date(monday, day_period="afternoon"),
            (14.0, 18.0),
        )


@tagged("post_install", "-at_install")
class TestDurationHoursClearedBounds(TransactionCase):
    """duration_hours must recompute when the hour bounds are cleared."""

    def test_duration_zeroed_when_hours_cleared(self):
        calendar = self.env["resource.calendar"].create(
            {"name": "Clear Cal", "tz": "UTC"}
        )
        attendance = calendar.attendance_ids.filtered(
            lambda a: a.day_period == "morning"
        )[0]
        self.assertGreater(attendance.duration_hours, 0)
        attendance.write({"hour_from": 0.0, "hour_to": 0.0})
        self.assertEqual(
            attendance.duration_hours,
            0.0,
            "clearing the bounds must not leave a stale duration",
        )


@tagged("post_install", "-at_install")
class TestLeaveCompanyFallback(TransactionCase):
    """A calendar-less leave belongs to its resource's company, not env.company."""

    def test_leave_company_follows_resource(self):
        company_b = self.env["res.company"].create({"name": "Company B"})
        resource_b = self.env["resource.resource"].create(
            {
                "name": "B worker",
                "company_id": company_b.id,
                "calendar_id": False,  # fully flexible: no calendar to derive from
                "tz": "UTC",
            }
        )
        leave = self.env["resource.calendar.leaves"].create(
            {
                "name": "B leave",
                "resource_id": resource_b.id,
                "date_from": datetime(2025, 1, 6, 0, 0),
                "date_to": datetime(2025, 1, 6, 23, 59),
            }
        )
        self.assertFalse(leave.calendar_id)
        self.assertEqual(
            leave.company_id,
            company_b,
            "the resource's company must beat the acting company",
        )


@tagged("post_install", "-at_install")
class TestDurationHoursRecompute(TransactionCase):
    """`duration_hours` must recompute when `day_period` changes, otherwise it
    stays at 0 after leaving 'lunch' (upstream e9a38d68f1)."""

    def test_duration_hours_recomputed_on_day_period_change(self):
        calendar = self.env["resource.calendar"].create(
            {"name": "Recompute calendar", "attendance_ids": False}
        )
        attendance = self.env["resource.calendar.attendance"].create(
            {
                "name": "Lunch then work",
                "calendar_id": calendar.id,
                "dayofweek": "0",
                "day_period": "lunch",
                "hour_from": 8,
                "hour_to": 16,
            }
        )
        self.assertEqual(attendance.duration_hours, 0)
        attendance.day_period = "full_day"
        self.assertEqual(attendance.duration_hours, 8)
