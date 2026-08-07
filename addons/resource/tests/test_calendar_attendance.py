# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestResourceCalendarAttendance(TransactionCase):
    """Pure computes/onchanges on resource.calendar.attendance."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "Attendance Calendar", "tz": "UTC"}
        )

    def _attendance(self, hour_from, hour_to, day_period="morning"):
        return self.env["resource.calendar.attendance"].create(
            {
                "name": "Slot",
                "calendar_id": self.calendar.id,
                "dayofweek": "0",
                "hour_from": hour_from,
                "hour_to": hour_to,
                "day_period": day_period,
            }
        )

    def test_duration_hours_is_span(self):
        """duration_hours is the span, and zero for a lunch period."""
        self.assertEqual(self._attendance(8.0, 12.0).duration_hours, 4.0)
        self.assertEqual(
            self._attendance(12.0, 13.0, day_period="lunch").duration_hours, 0.0
        )

    def test_onchange_hours_clamps_bounds(self):
        """The onchange clamps hours into range and keeps from <= to."""
        # Use an in-memory record: the onchange runs before the stored-write
        # constraint would reject the out-of-range input.
        attendance = self.env["resource.calendar.attendance"].new(
            {
                "calendar_id": self.calendar.id,
                "dayofweek": "0",
                "hour_from": 25.0,
                "hour_to": -1.0,
                "day_period": "morning",
            }
        )
        attendance._onchange_hours()
        self.assertEqual(attendance.hour_from, 23.99)
        # hour_to is clamped up to hour_from (order preserved)
        self.assertEqual(attendance.hour_to, attendance.hour_from)

    def test_duration_days_by_period(self):
        """duration_days is 0 for lunch and 1 for a full day."""
        self.assertEqual(
            self._attendance(12.0, 13.0, day_period="lunch").duration_days, 0
        )
        self.assertEqual(
            self._attendance(8.0, 18.0, day_period="full_day").duration_days, 1
        )

    def test_get_week_type_parity(self):
        """get_week_type returns the alternating 0/1 parity for consecutive weeks."""
        Attendance = self.env["resource.calendar.attendance"]
        first = Attendance.get_week_type(date(2024, 1, 1))
        next_week = Attendance.get_week_type(date(2024, 1, 8))
        self.assertIn(first, (0, 1))
        self.assertNotEqual(first, next_week)

    def test_check_hours_rejects_out_of_range_creation(self):
        """A real create with an out-of-range hour_from raises ValidationError."""
        with self.assertRaises(ValidationError):
            self.env["resource.calendar.attendance"].create(
                {
                    "name": "Out Of Range Slot",
                    "calendar_id": self.calendar.id,
                    "dayofweek": "0",
                    "hour_from": 25.0,
                    "hour_to": 12.0,
                    "day_period": "morning",
                }
            )

    def test_check_hours_rejects_reversed_ordering(self):
        """A real create with hour_from after hour_to raises ValidationError."""
        with self.assertRaises(ValidationError):
            self.env["resource.calendar.attendance"].create(
                {
                    "name": "Reversed Slot",
                    "calendar_id": self.calendar.id,
                    "dayofweek": "0",
                    "hour_from": 14.0,
                    "hour_to": 8.0,
                    "day_period": "morning",
                }
            )
