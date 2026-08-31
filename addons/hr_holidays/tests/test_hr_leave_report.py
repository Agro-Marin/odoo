from datetime import date

from odoo.tests import tagged

from odoo.addons.hr_holidays.tests.common import TestHrHolidaysCommon


@tagged("post_install", "-at_install")
class TestHrLeaveReport(TestHrHolidaysCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.leave_type = cls.env["hr.leave.type"].create(
            {
                "name": "Report Test Type",
                "requires_allocation": True,
                "request_unit": "day",
                "leave_validation_type": "hr",
                "allocation_validation_type": "no_validation",
                "employee_requests": True,
                "company_id": cls.company.id,
            }
        )
        cls.allocation = cls.env["hr.leave.allocation"].create(
            {
                "name": "Report Test Allocation",
                "employee_id": cls.employee_emp_id,
                "holiday_status_id": cls.leave_type.id,
                "number_of_days": 10,
            }
        )
        cls.allocation.action_approve()
        cls.leave = cls.env["hr.leave"].create(
            {
                "employee_id": cls.employee_emp_id,
                "holiday_status_id": cls.leave_type.id,
                "request_date_from": date(2026, 9, 7),
                "request_date_to": date(2026, 9, 8),
            }
        )

    def _report_row(self, leave_type, record):
        rows = self.env["hr.leave.report"].search(
            [
                ("employee_id", "=", self.employee_emp_id),
                ("leave_type", "=", leave_type),
            ]
        )
        return rows.filtered(
            lambda row, record=record: record in (row.leave_id, row.allocation_id)
        )

    def test_request_row_points_at_the_leave(self):
        row = self._report_row("request", self.leave)
        self.assertTrue(row, "the leave request has no row in hr.leave.report")
        self.assertEqual(
            row.leave_id,
            self.leave,
            "a 'request' row must carry its hr.leave in leave_id",
        )
        self.assertFalse(
            row.allocation_id,
            "a 'request' row must not name an allocation -- when the UNION "
            "branches were swapped the leave's id landed here, so the id "
            "resolved to whatever allocation happened to share it",
        )

    def test_allocation_row_points_at_the_allocation(self):
        row = self._report_row("allocation", self.allocation)
        self.assertTrue(row, "the allocation has no row in hr.leave.report")
        self.assertEqual(row.allocation_id, self.allocation)
        self.assertFalse(row.leave_id)

    def test_action_view_record_opens_the_right_model(self):
        request_action = self._report_row("request", self.leave).action_view_record()
        self.assertEqual(request_action["res_model"], "hr.leave")
        self.assertEqual(request_action["res_id"], self.leave.id)

        allocation_action = self._report_row(
            "allocation", self.allocation
        ).action_view_record()
        self.assertEqual(allocation_action["res_model"], "hr.leave.allocation")
        self.assertEqual(allocation_action["res_id"], self.allocation.id)


@tagged("post_install", "-at_install")
class TestHrLeaveEmployeeTypeReport(TestHrHolidaysCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.leave_type = cls.env["hr.leave.type"].create(
            {
                "name": "Balance Report Type",
                "requires_allocation": True,
                "request_unit": "day",
                "leave_validation_type": "hr",
                "allocation_validation_type": "hr",
                "employee_requests": True,
                "company_id": cls.company.id,
            }
        )

    def _allocate(self, days, state):
        allocation = self.env["hr.leave.allocation"].create(
            {
                "name": f"{state} {days}",
                "employee_id": self.employee_emp_id,
                "holiday_status_id": self.leave_type.id,
                "number_of_days": days,
            }
        )
        if state == "validate":
            allocation.action_approve()
            allocation.action_approve()
        elif state == "refuse":
            allocation.action_refuse()
        return allocation

    def _rows(self):
        return self.env["hr.leave.employee.type.report"].search(
            [
                ("employee_id", "=", self.employee_emp_id),
                ("leave_type", "=", self.leave_type.id),
            ]
        )

    def test_balance_is_carried_by_a_validated_allocation(self):
        refused = self._allocate(99, "refuse")
        approved = self._allocate(10, "validate")
        self.assertLess(
            refused.id,
            approved.id,
            "the refused allocation must be the lower id for this test to bite",
        )
        left = self._rows().filtered(lambda row: row.holiday_status == "left")
        carrying = left.filtered(lambda row: row.number_of_days)
        self.assertEqual(
            sum(left.mapped("number_of_days")),
            10.0,
            "only the validated allocation contributes to the remaining balance",
        )
        self.assertEqual(
            carrying.mapped("state"),
            ["validate"],
            "the balance must sit on a validated row; picking the overall minimum "
            "allocation id parked it on a refused one whenever a refused request "
            "preceded an approved one, so a pivot sliced by state credited the "
            "whole balance to Refused",
        )

    def test_taken_leaves_reduce_the_balance(self):
        self._allocate(10, "validate")
        leave = self.env["hr.leave"].create(
            {
                "employee_id": self.employee_emp_id,
                "holiday_status_id": self.leave_type.id,
                "request_date_from": date(2026, 9, 7),
                "request_date_to": date(2026, 9, 8),
            }
        )
        leave.action_approve()
        rows = self._rows()
        left = sum(
            rows.filtered(lambda row: row.holiday_status == "left").mapped(
                "number_of_days"
            )
        )
        taken = sum(
            rows.filtered(lambda row: row.holiday_status == "taken").mapped(
                "number_of_days"
            )
        )
        self.assertEqual(taken, leave.number_of_days)
        self.assertEqual(
            left,
            10.0 - leave.number_of_days,
            "the 'left' figure is the validated allocation minus validated leaves",
        )
