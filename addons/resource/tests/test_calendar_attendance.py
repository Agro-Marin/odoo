from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestResourceCalendarAttendance(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "Attendance Calendar", "tz": "UTC"}
        )

    def _attendance(self, hour_from, hour_to, day_period="morning", dayofweek="5"):
        return self.env["resource.calendar.attendance"].create(
            {
                "name": "Slot",
                "calendar_id": self.calendar.id,
                "dayofweek": dayofweek,
                "hour_from": hour_from,
                "hour_to": hour_to,
                "day_period": day_period,
            }
        )

    def test_duration_hours_is_span(self):
        self.assertEqual(self._attendance(8.0, 12.0).duration_hours, 4.0)
        self.assertEqual(
            self._attendance(12.0, 13.0, day_period="lunch").duration_hours, 0.0
        )

    def test_onchange_hours_clamps_bounds(self):
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
        self.assertEqual(attendance.hour_to, attendance.hour_from)

    def test_duration_days_by_period(self):
        self.assertEqual(
            self._attendance(12.0, 13.0, day_period="lunch").duration_days, 0
        )
        self.assertEqual(
            self._attendance(
                8.0, 18.0, day_period="full_day", dayofweek="6"
            ).duration_days,
            1,
        )

    def test_get_week_type_parity(self):
        Attendance = self.env["resource.calendar.attendance"]
        first = Attendance.get_week_type(date(2024, 1, 1))
        next_week = Attendance.get_week_type(date(2024, 1, 8))
        self.assertIn(first, (0, 1))
        self.assertNotEqual(first, next_week)

    def test_check_hours_rejects_out_of_range_creation(self):
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
