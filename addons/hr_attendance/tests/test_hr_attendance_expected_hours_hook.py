from datetime import date, datetime
from unittest.mock import patch

from freezegun import freeze_time

from odoo import Command
from odoo.tests.common import TransactionCase, tagged

RULE_MODEL = "odoo.addons.hr_attendance.models.hr_attendance_overtime_rule"


@tagged("post_install", "-at_install")
class TestExpectedHoursExtensionPoint(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create({"name": "Hook Inc."})
        cls.company.resource_calendar_id = cls.env["resource.calendar"].create(
            {
                "name": "Eight hours a day",
                "company_id": cls.company.id,
                "tz": "UTC",
                "attendance_ids": [
                    Command.clear(),
                    *(
                        Command.create(
                            {
                                "name": day,
                                "dayofweek": str(index),
                                "hour_from": 8,
                                "hour_to": 16,
                                "day_period": "morning",
                            }
                        )
                        for index, day in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri"])
                    ),
                ],
            }
        )
        cls.ruleset = cls.env["hr.attendance.overtime.ruleset"].create(
            {
                "name": "From the employee's schedule",
                "company_id": cls.company.id,
                "rule_ids": [
                    Command.create(
                        {
                            "name": "Beyond the scheduled day",
                            "base_off": "quantity",
                            "quantity_period": "day",
                            "expected_hours_from_contract": True,
                            "paid": True,
                            "amount_rate": 1.0,
                        }
                    )
                ],
            }
        )
        cls.employee = cls.env["hr.employee"].create(
            {
                "name": "Hooked",
                "company_id": cls.company.id,
                "tz": "UTC",
                "date_version": date(2020, 1, 1),
                "contract_date_start": date(2020, 1, 1),
                "resource_calendar_id": cls.company.resource_calendar_id.id,
                "ruleset_id": cls.ruleset.id,
            }
        )

    def _overtime_for_a_ten_hour_monday(self):
        with freeze_time("2021-01-04"):
            attendance = self.env["hr.attendance"].create(
                {
                    "employee_id": self.employee.id,
                    "check_in": datetime(2021, 1, 4, 8, 0),
                    "check_out": datetime(2021, 1, 4, 18, 0),
                }
            )
            return attendance.employee_id.total_overtime

    def test_the_schedule_supplies_the_expected_hours(self):
        self.assertAlmostEqual(
            self._overtime_for_a_ten_hour_monday(),
            2.0,
            2,
            "ten hours worked against an eight-hour scheduled day is two hours over",
        )

    def test_the_hook_is_told_which_employee_it_is_answering_for(self):
        seen = []

        def spy(rule, start, stop, schedule, employee):
            seen.append((start, stop, employee))
            return 8.0

        with patch(
            f"{RULE_MODEL}.HrAttendanceOvertimeRule._get_expected_hours_for_period",
            autospec=True,
            side_effect=spy,
        ):
            self._overtime_for_a_ten_hour_monday()
        self.assertTrue(seen, "the engine must call the hook")
        self.assertTrue(
            all(employee == self.employee for _start, _stop, employee in seen),
            "an override decides expected hours from the employee's contract or "
            "planning, so the hook is useless unless it is told which employee "
            "the period belongs to. Its predecessor took the version; dropping "
            "that made the extension point unimplementable.",
        )

    def test_an_override_of_the_hook_changes_the_overtime(self):
        with patch(
            f"{RULE_MODEL}.HrAttendanceOvertimeRule._get_expected_hours_for_period",
            return_value=6.0,
        ):
            overtime = self._overtime_for_a_ten_hour_monday()
        self.assertAlmostEqual(
            overtime,
            4.0,
            2,
            "overriding `_get_expected_hours_for_period` must change the "
            "overtime the engine produces; if it does not, the engine is no "
            "longer calling it and every override of it is dead",
        )
