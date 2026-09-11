from odoo import SUPERUSER_ID
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import TestHrHolidaysCommon


@tagged("post_install", "-at_install")
class TestAllocationApprovalEngine(TestHrHolidaysCommon):
    """Allocations are approved through approval.request, and still behave as allocations.

    employee_emp's leave manager is user_responsible; user_hruser is a Time Off
    Officer and user_hrmanager a Time Off Manager.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category = cls.env.ref("hr_holidays.approval_category_allocation")

    def _allocation(self, validation_type, user=None):
        leave_type = self.env["hr.leave.type"].create(
            {
                "name": f"Engine allocation {validation_type}",
                "requires_allocation": True,
                "employee_requests": True,
                "allocation_validation_type": validation_type,
                "request_unit": "day",
            }
        )
        model = self.env["hr.leave.allocation"]
        if user != SUPERUSER_ID:
            model = model.with_user(user or self.user_employee_id)
        return model.create(
            {
                "name": f"Engine allocation {validation_type}",
                "employee_id": self.employee_emp_id,
                "holiday_status_id": leave_type.id,
                "number_of_days": 2,
                "allocation_type": "regular",
            }
        )

    def test_an_allocation_raises_a_pending_request_in_its_category(self):
        allocation = self._allocation("manager")

        self.assertEqual(allocation.state, "confirm")
        request = allocation.sudo().approval_request_id
        self.assertEqual(request.state, "pending")
        self.assertEqual(request.category_id, self.category)
        self.assertEqual(request.request_owner_id, self.user_employee)
        self.assertIn(self.user_responsible, request.approver_ids.user_id)

    def test_an_allocation_that_needs_no_validation_raises_no_request(self):
        allocation = self._allocation("no_validation")

        self.assertEqual(allocation.state, "validate")
        self.assertFalse(allocation.sudo().approval_request_id)

    def test_the_leave_manager_approves_and_the_employee_cannot(self):
        allocation = self._allocation("manager")

        with self.assertRaises(UserError):
            allocation.with_user(self.user_employee_id).action_approve()
        allocation.with_user(self.user_responsible_id).action_approve()

        self.assertEqual(allocation.state, "validate")
        self.assertEqual(allocation.approver_id, self.employee_responsible)
        self.assertEqual(allocation.sudo().approval_request_id.state, "approved")

    def test_double_validation_goes_through_the_manager_then_an_officer(self):
        allocation = self._allocation("both")

        allocation.with_user(self.user_responsible_id).action_approve()
        self.assertEqual(allocation.state, "validate1")
        self.assertEqual(allocation.sudo().approval_request_id.state, "pending")

        allocation.with_user(self.user_hruser_id).action_approve()
        self.assertEqual(allocation.state, "validate")
        self.assertEqual(allocation.second_approver_id, self.employee_hruser)
        self.assertEqual(allocation.sudo().approval_request_id.state, "approved")

    def test_an_officer_refuses_a_validated_allocation(self):
        allocation = self._allocation("hr")
        allocation.with_user(self.user_hruser_id).action_approve()

        allocation.with_user(self.user_hruser_id).action_refuse()

        self.assertEqual(allocation.state, "refuse")
        request = allocation.sudo().approval_request_id
        self.assertEqual(request.state, "refused")
        self.assertEqual(request.revoked_state, "refused")

    def test_approving_the_request_validates_the_allocation(self):
        allocation = self._allocation("manager")

        allocation.sudo().approval_request_id.with_user(
            self.user_responsible_id
        ).action_approve()

        self.assertEqual(allocation.state, "validate")
        self.assertEqual(allocation.approver_id, self.employee_responsible)

    def test_the_request_is_not_cancelled_from_the_approvals_app(self):
        allocation = self._allocation("manager")

        with self.assertRaises(UserError):
            allocation.sudo().approval_request_id.with_user(
                self.user_employee_id
            ).action_cancel()
        self.assertEqual(allocation.state, "confirm")

    def test_the_superuser_creates_an_allocation_without_a_request(self):
        allocation = self._allocation("both", user=SUPERUSER_ID)

        self.assertFalse(allocation.approval_request_id)
        allocation.action_approve()
        self.assertEqual(allocation.state, "validate")

    def test_the_request_belongs_to_the_employee_not_its_creator(self):
        allocation = self._allocation("manager", user=self.user_hruser_id)

        self.assertEqual(
            allocation.sudo().approval_request_id.request_owner_id, self.user_employee
        )

    def test_a_request_cancelled_by_the_engine_refuses_the_allocation(self):
        allocation = self._allocation("manager")

        allocation.sudo().approval_request_id._force_terminal("cancelled", "Expired")

        self.assertEqual(allocation.state, "refuse")

    def test_an_allocation_first_approved_before_the_engine_keeps_that_decision(self):
        allocation = self._allocation("both", user=SUPERUSER_ID)
        allocation.write(
            {"state": "validate1", "approver_id": self.employee_responsible.id}
        )
        self.assertFalse(allocation.approval_request_id)

        allocation._backfill_approval_requests()

        request = allocation.sudo().approval_request_id
        self.assertEqual(request.state, "pending")
        row = request.approver_ids.filtered(
            lambda row: row.user_id == self.user_responsible
        )
        self.assertEqual(row.decided_by_user_id, self.user_responsible)
        self.assertEqual(len(row.decided_step_ids), 1)
        self.assertEqual(
            request._get_open_steps() & row.decided_step_ids,
            row.decided_step_ids.browse(),
        )
        self.assertEqual(allocation.state, "validate1")

    def test_an_officer_only_allocation_is_asked_for_its_first_approval(self):
        leave_type = self.env["hr.leave.type"].create(
            {
                "name": "Engine allocation asked by an officer",
                "requires_allocation": True,
                "employee_requests": True,
                "allocation_validation_type": "hr",
                "request_unit": "day",
                "responsible_ids": [(6, 0, self.user_hruser.ids)],
            }
        )

        allocation = (
            self.env["hr.leave.allocation"]
            .with_user(self.user_employee_id)
            .create(
                {
                    "name": "Engine allocation asked by an officer",
                    "employee_id": self.employee_emp_id,
                    "holiday_status_id": leave_type.id,
                    "number_of_days": 2,
                    "allocation_type": "regular",
                }
            )
        )

        self.assertRecordValues(
            allocation.sudo().activity_ids,
            [
                {
                    "user_id": self.user_hruser_id,
                    "activity_type_id": self.env.ref(
                        "hr_holidays.mail_act_leave_allocation_approval"
                    ).id,
                }
            ],
        )
