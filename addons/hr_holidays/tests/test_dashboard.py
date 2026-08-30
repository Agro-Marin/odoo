from datetime import datetime

from odoo.addons.hr_holidays.tests.common import TestHrHolidaysCommon


class TestDashboard(TestHrHolidaysCommon):
    def test_dashboard_special_days(self):
        self.uid = self.user_hrmanager.id
        employee = self.env.user.employee_id
        other_calendar = (
            self.env["resource.calendar"]
            .sudo()
            .create(
                {
                    "name": "Other calendar",
                }
            )
        )

        mandatory_day_vals = [
            {
                "name": "Super Event (employee schedule)",
                "company_id": employee.company_id.id,
                "start_date": datetime(2021, 6, 12),
                "end_date": datetime(2021, 6, 12),
                "resource_calendar_id": employee.resource_calendar_id.id,
            },
            {
                "name": "Super Event (no schedule)",
                "company_id": employee.company_id.id,
                "start_date": datetime(2021, 6, 12),
                "end_date": datetime(2021, 6, 12),
            },
            {
                "name": "Super Event (other schedule)",
                "company_id": employee.company_id.id,
                "start_date": datetime(2021, 6, 12),
                "end_date": datetime(2021, 6, 12),
                "resource_calendar_id": other_calendar.id,
            },
        ]
        self.env["hr.leave.mandatory.day"].create(mandatory_day_vals)

        public_holiday_vals = [
            {
                "name": "Public holiday (employee schedule)",
                "date_from": "2021-06-15 06:00:00",
                "date_to": "2021-06-15 15:00:00",
                "calendar_id": employee.resource_calendar_id.id,
            },
            {
                "name": "Public holiday (no schedule)",
                "date_from": "2021-06-16 06:00:00",
                "date_to": "2021-06-16 15:00:00",
            },
            {
                "name": "Public holiday (other schedule)",
                "date_from": "2021-06-17 06:00:00",
                "date_to": "2021-06-17 15:00:00",
                "calendar_id": other_calendar.id,
            },
        ]
        self.env["resource.calendar.leaves"].create(public_holiday_vals)

        dashboard_data = self.env["hr.employee"].get_special_days_data(
            "2021-06-01", "2021-07-01"
        )

        self.assertEqual(
            {d["title"] for d in dashboard_data["mandatoryDays"]},
            {"Super Event (employee schedule)", "Super Event (no schedule)"},
        )
        self.assertEqual(
            {d["title"] for d in dashboard_data["bankHolidays"]},
            {"Public holiday (employee schedule)", "Public holiday (no schedule)"},
        )

    def test_pending_allocations_action_can_open_a_record(self):
        """The dashboard's pending allocation counter must open onto a form.

        Clicking "Allocation Requests" on the time off dashboard hands the web
        client an action. With a list view alone the rows are inert: there is
        nowhere for the client to navigate to, so an employee can see that they
        have pending allocations but cannot open a single one of them.
        """
        action = (
            self.env["hr.leave"].with_user(self.user_employee).open_pending_requests()
        )

        self.assertEqual(action["res_model"], "hr.leave.allocation")
        self.assertIn(
            "form",
            [view_mode for __, view_mode in action["views"]],
            "The action must carry a form view or its list rows cannot be opened.",
        )
