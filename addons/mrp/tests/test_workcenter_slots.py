from datetime import datetime

from freezegun import freeze_time

from odoo import Command
from odoo.tests import tagged

from . import common


@tagged("post_install", "-at_install")
class TestWorkcenterFirstAvailableSlot(common.TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create(
            {
                "name": "Slots 08-16 UTC",
                "tz": "UTC",
                "attendance_ids": [
                    Command.create(
                        {
                            "name": f"{day} 08-16",
                            "dayofweek": str(day),
                            "hour_from": 8.0,
                            "hour_to": 16.0,
                            "day_period": "morning",
                        }
                    )
                    for day in range(5)
                ],
            }
        )
        cls.workcenter = cls.env["mrp.workcenter"].create(
            {"name": "Slot workcenter", "resource_calendar_id": cls.calendar.id}
        )

    def _reserve(self, date_start, date_end, enforcement_mode="soft"):
        return self.env["resource.reservation"].create(
            {
                "name": "Occupied",
                "resource_id": self.workcenter.resource_id.id,
                "date_start": date_start,
                "date_end": date_end,
                "allocated_percentage": 100.0,
                "enforcement_mode": enforcement_mode,
            }
        )

    @freeze_time("2024-01-01 06:00:00")
    def test_forward_takes_the_start_of_an_empty_day(self):
        start, stop = self.workcenter._get_first_available_slot(
            datetime(2024, 1, 1, 8, 0), 60
        )
        self.assertEqual(start, datetime(2024, 1, 1, 8, 0))
        self.assertEqual(stop, datetime(2024, 1, 1, 9, 0))

    @freeze_time("2024-01-01 06:00:00")
    def test_forward_starts_when_the_shift_opens_not_before_it(self):
        start, stop = self.workcenter._get_first_available_slot(
            datetime(2024, 1, 1, 5, 0), 120
        )
        self.assertEqual(start, datetime(2024, 1, 1, 8, 0))
        self.assertEqual(stop, datetime(2024, 1, 1, 10, 0))

    @freeze_time("2024-01-01 06:00:00")
    def test_forward_skips_an_occupied_interval(self):
        self._reserve(datetime(2024, 1, 1, 8, 0), datetime(2024, 1, 1, 12, 0))
        start, stop = self.workcenter._get_first_available_slot(
            datetime(2024, 1, 1, 8, 0), 60
        )
        self.assertEqual(start, datetime(2024, 1, 1, 12, 0))
        self.assertEqual(stop, datetime(2024, 1, 1, 13, 0))

    @freeze_time("2024-01-01 06:00:00")
    def test_forward_fits_into_the_gap_between_two_reservations(self):
        self._reserve(datetime(2024, 1, 1, 8, 0), datetime(2024, 1, 1, 10, 0))
        self._reserve(datetime(2024, 1, 1, 11, 0), datetime(2024, 1, 1, 16, 0))
        start, stop = self.workcenter._get_first_available_slot(
            datetime(2024, 1, 1, 8, 0), 60
        )
        self.assertEqual(start, datetime(2024, 1, 1, 10, 0))
        self.assertEqual(stop, datetime(2024, 1, 1, 11, 0))

    @freeze_time("2024-01-01 06:00:00")
    def test_forward_rejects_a_gap_that_is_too_short(self):
        self._reserve(datetime(2024, 1, 1, 8, 0), datetime(2024, 1, 1, 10, 0))
        self._reserve(datetime(2024, 1, 1, 11, 0), datetime(2024, 1, 1, 13, 0))
        start, stop = self.workcenter._get_first_available_slot(
            datetime(2024, 1, 1, 8, 0), 90
        )
        self.assertEqual(start, datetime(2024, 1, 1, 13, 0))
        self.assertEqual(stop, datetime(2024, 1, 1, 14, 30))

    @freeze_time("2024-01-01 06:00:00")
    def test_forward_rolls_over_to_the_next_working_day(self):
        self._reserve(datetime(2024, 1, 1, 8, 0), datetime(2024, 1, 1, 16, 0))
        self._reserve(datetime(2024, 1, 2, 8, 0), datetime(2024, 1, 2, 16, 0))
        self._reserve(datetime(2024, 1, 3, 8, 0), datetime(2024, 1, 3, 16, 0))
        self._reserve(datetime(2024, 1, 4, 8, 0), datetime(2024, 1, 4, 16, 0))
        self._reserve(datetime(2024, 1, 5, 8, 0), datetime(2024, 1, 5, 16, 0))
        start, stop = self.workcenter._get_first_available_slot(
            datetime(2024, 1, 1, 8, 0), 60
        )
        self.assertEqual(start, datetime(2024, 1, 8, 8, 0))
        self.assertEqual(stop, datetime(2024, 1, 8, 9, 0))

    @freeze_time("2024-01-01 06:00:00")
    def test_forward_spans_two_days_when_the_shift_is_too_short(self):
        start, stop = self.workcenter._get_first_available_slot(
            datetime(2024, 1, 1, 8, 0), 600
        )
        self.assertEqual(start, datetime(2024, 1, 1, 8, 0))
        self.assertEqual(stop, datetime(2024, 1, 2, 10, 0))

    @freeze_time("2024-01-01 06:00:00")
    def test_forward_ignores_the_reservations_it_is_told_to(self):
        own = self._reserve(datetime(2024, 1, 1, 8, 0), datetime(2024, 1, 1, 16, 0))
        blocked, _stop = self.workcenter._get_first_available_slot(
            datetime(2024, 1, 1, 8, 0), 60
        )
        self.assertEqual(blocked, datetime(2024, 1, 2, 8, 0))
        start, stop = self.workcenter._get_first_available_slot(
            datetime(2024, 1, 1, 8, 0), 60, reservations_to_ignore=own
        )
        self.assertEqual(start, datetime(2024, 1, 1, 8, 0))
        self.assertEqual(stop, datetime(2024, 1, 1, 9, 0))

    @freeze_time("2024-01-01 06:00:00")
    def test_forward_avoids_extra_leave_slots(self):
        start, stop = self.workcenter._get_first_available_slot(
            datetime(2024, 1, 1, 8, 0),
            60,
            extra_leaves_slots=[
                (datetime(2024, 1, 1, 8, 0), datetime(2024, 1, 1, 14, 0))
            ],
        )
        self.assertEqual(start, datetime(2024, 1, 1, 14, 0))
        self.assertEqual(stop, datetime(2024, 1, 1, 15, 0))

    @freeze_time("2024-01-01 06:00:00")
    def test_forward_rounds_a_zero_duration_up_to_a_second(self):
        start, stop = self.workcenter._get_first_available_slot(
            datetime(2024, 1, 1, 8, 0), 0
        )
        self.assertEqual(start, datetime(2024, 1, 1, 8, 0))
        self.assertEqual(stop, datetime(2024, 1, 1, 8, 0, 1))

    @freeze_time("2024-01-01 06:00:00")
    def test_a_workcenter_that_never_works_reports_no_slot(self):
        idle = self.env["mrp.workcenter"].create(
            {
                "name": "Closed workcenter",
                "resource_calendar_id": self.env["resource.calendar"]
                .create({"name": "Never open", "tz": "UTC", "attendance_ids": []})
                .id,
            }
        )
        start, message = idle._get_first_available_slot(datetime(2024, 1, 1, 8, 0), 60)
        self.assertFalse(start)
        self.assertIn("No available slot", message)

    @freeze_time("2024-01-01 06:00:00")
    def test_the_iteration_bound_is_configurable(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "mrp.workcenter_max_planning_iterations", "1"
        )
        for day in range(1, 15):
            date = datetime(2024, 1, day, 8, 0)
            if date.weekday() < 5:
                self._reserve(date, datetime(2024, 1, day, 16, 0))
        start, message = self.workcenter._get_first_available_slot(
            datetime(2024, 1, 1, 8, 0), 60
        )
        self.assertFalse(start)
        self.assertIn("No available slot", message)

    @freeze_time("2024-01-01 06:00:00")
    def test_backward_takes_the_end_of_the_window(self):
        start, stop = self.workcenter._get_first_available_slot(
            datetime(2024, 1, 10, 16, 0), 60, forward=False
        )
        self.assertEqual(stop, datetime(2024, 1, 10, 16, 0))
        self.assertEqual(start, datetime(2024, 1, 10, 15, 0))

    @freeze_time("2024-01-01 06:00:00")
    def test_backward_skips_an_occupied_interval(self):
        self._reserve(datetime(2024, 1, 10, 14, 0), datetime(2024, 1, 10, 16, 0))
        start, stop = self.workcenter._get_first_available_slot(
            datetime(2024, 1, 10, 16, 0), 60, forward=False
        )
        self.assertEqual(stop, datetime(2024, 1, 10, 14, 0))
        self.assertEqual(start, datetime(2024, 1, 10, 13, 0))

    @freeze_time("2024-01-01 06:00:00")
    def test_backward_walks_back_over_a_closed_day(self):
        start, stop = self.workcenter._get_first_available_slot(
            datetime(2024, 1, 6, 12, 0), 60, forward=False
        )
        self.assertEqual(stop, datetime(2024, 1, 5, 16, 0))
        self.assertEqual(start, datetime(2024, 1, 5, 15, 0))
