from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import SUPERUSER_ID
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import date_utils

from .common import TestHrHolidaysCommon


@tagged("post_install", "-at_install")
class TestLeaveApprovalEngine(TestHrHolidaysCommon):
    """Time off is approved through approval.request, and still behaves as time off.

    employee_emp's leave manager is user_responsible; user_hruser is a Time Off
    Officer and user_hrmanager a Time Off Manager (both officers for approving).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.leave_day = date_utils.start_of(
            date.today() + relativedelta(days=14), "week"
        )
        cls.category = cls.env.ref("hr_holidays.approval_category_leave")

    def _leave_type(self, validation_type):
        return self.env["hr.leave.type"].create(
            {
                "name": f"Engine {validation_type}",
                "requires_allocation": False,
                "request_unit": "day",
                "leave_validation_type": validation_type,
            }
        )

    def _leave(self, validation_type, days=1, leave_type=None, user=None):
        leave_type = leave_type or self._leave_type(validation_type)
        env = self.env["hr.leave"]
        if user != SUPERUSER_ID:
            env = env.with_user(user or self.user_employee_id)
        return env.create(
            {
                "name": f"Engine leave {leave_type.leave_validation_type}",
                "employee_id": self.employee_emp_id,
                "holiday_status_id": leave_type.id,
                "request_date_from": self.leave_day,
                "request_date_to": self.leave_day + relativedelta(days=days - 1),
            }
        )

    # -- the request a leave raises --------------------------------------

    def test_a_leave_raises_a_pending_request_in_the_time_off_category(self):
        leave = self._leave("manager")

        self.assertEqual(leave.state, "confirm")
        request = leave.sudo().approval_request_id
        self.assertEqual(request.state, "pending")
        self.assertEqual(request.category_id, self.category)
        self.assertIn(self.user_responsible, request.approver_ids.user_id)

    def test_a_leave_that_needs_no_validation_raises_no_request(self):
        leave = self._leave("no_validation")

        self.assertEqual(leave.state, "validate")
        self.assertFalse(leave.sudo().approval_request_id)

    # -- manager validation ------------------------------------------------

    def test_the_leave_manager_approves_and_the_employee_cannot(self):
        leave = self._leave("manager")

        with self.assertRaises(UserError):
            leave.with_user(self.user_employee_id).action_approve()
        leave.with_user(self.user_responsible_id).action_approve()

        self.assertEqual(leave.state, "validate")
        self.assertEqual(leave.sudo().approval_request_id.state, "approved")
        self.assertEqual(leave.first_approver_id, self.employee_responsible)

    def test_an_officer_approves_a_manager_validated_leave_too(self):
        leave = self._leave("manager")

        leave.with_user(self.user_hruser_id).action_approve()

        self.assertEqual(leave.state, "validate")

    # -- double validation -------------------------------------------------

    def test_double_validation_goes_through_the_manager_then_an_officer(self):
        leave = self._leave("both")

        leave.with_user(self.user_responsible_id).action_approve()
        self.assertEqual(leave.state, "validate1")
        self.assertEqual(leave.sudo().approval_request_id.state, "pending")
        self.assertEqual(leave.first_approver_id, self.employee_responsible)

        leave.with_user(self.user_hruser_id).action_approve()
        self.assertEqual(leave.state, "validate")
        self.assertEqual(leave.second_approver_id, self.employee_hruser)
        self.assertEqual(leave.sudo().approval_request_id.state, "approved")

    def test_one_time_off_manager_decision_completes_double_validation(self):
        leave = self._leave("both")

        leave.with_user(self.user_hrmanager_id).action_approve()

        self.assertEqual(leave.state, "validate")
        self.assertEqual(leave.sudo().approval_request_id.state, "approved")

    # -- moves after validation, which time off policy authorizes ----------

    def test_an_officer_refuses_a_validated_leave_and_the_decisions_stay(self):
        leave = self._leave("manager")
        leave.with_user(self.user_responsible_id).action_approve()

        leave.with_user(self.user_hruser_id).action_refuse()

        self.assertEqual(leave.state, "refuse")
        request = leave.sudo().approval_request_id
        self.assertEqual(request.state, "refused")
        self.assertEqual(request.revoked_state, "refused")
        self.assertIn(
            "approved",
            request.approver_ids.filtered(
                lambda row: row.user_id == self.user_responsible
            ).mapped("state"),
        )

    def test_the_leave_manager_refuses_after_approving(self):
        leave = self._leave("manager")
        leave.with_user(self.user_responsible_id).action_approve()

        leave.with_user(self.user_responsible_id).action_refuse()

        self.assertEqual(leave.state, "refuse")
        self.assertEqual(leave.sudo().approval_request_id.state, "refused")

    def test_an_officer_refuses_a_pending_leave(self):
        leave = self._leave("both")

        leave.with_user(self.user_hruser_id).action_refuse()

        self.assertEqual(leave.state, "refuse")
        request = leave.sudo().approval_request_id
        self.assertEqual(request.state, "refused")
        self.assertEqual(
            request.approver_ids.filtered(
                lambda row: row.user_id == self.user_hruser
            ).decided_by_user_id,
            self.user_hruser,
        )

    def test_an_officer_sends_a_validated_leave_back_to_approval(self):
        leave = self._leave("hr")
        leave.with_user(self.user_hruser_id).action_approve()
        self.assertEqual(leave.state, "validate")

        leave.with_user(self.user_hruser_id).action_back_to_approval()

        self.assertEqual(leave.state, "confirm")
        self.assertEqual(leave.sudo().approval_request_id.state, "pending")
        self.assertFalse(
            any(
                "prior approval is no longer valid" in body
                for body in leave.sudo().message_ids.mapped("body")
            )
        )

    def test_an_employee_cancels_their_own_validated_leave(self):
        leave = self._leave("hr")
        leave.with_user(self.user_hruser_id).action_approve()

        leave.with_user(self.user_employee_id)._action_user_cancel("Plans changed")

        self.assertEqual(leave.state, "cancel")
        self.assertEqual(leave.sudo().approval_request_id.state, "cancelled")

    def test_an_officer_approves_a_refused_leave_again(self):
        leave = self._leave("hr")
        leave.with_user(self.user_hruser_id).action_refuse()

        leave.with_user(self.user_hruser_id).action_approve()

        self.assertEqual(leave.state, "validate")
        self.assertEqual(leave.sudo().approval_request_id.state, "approved")

    def test_the_leave_manager_refuses_at_second_approval(self):
        leave = self._leave("both")
        leave.with_user(self.user_responsible_id).action_approve()

        leave.with_user(self.user_responsible_id).action_refuse()

        self.assertEqual(leave.state, "refuse")
        request = leave.sudo().approval_request_id
        self.assertEqual(request.state, "refused")
        self.assertEqual(
            request.approver_ids.filtered(
                lambda row: row.user_id == self.user_responsible
            ).state,
            "approved",
        )

    # -- the system keeps the direct flow ----------------------------------

    def test_the_superuser_creates_time_off_without_a_request(self):
        leave = self._leave("both", user=SUPERUSER_ID)

        self.assertFalse(leave.approval_request_id)
        leave.action_approve()
        self.assertEqual(leave.state, "validate")

    def test_the_superuser_validating_a_leave_names_no_decider(self):
        leave = self._leave("both")

        leave.with_user(SUPERUSER_ID).action_approve()

        self.assertEqual(leave.state, "validate")
        request = leave.sudo().approval_request_id
        self.assertEqual(request.state, "approved")
        self.assertTrue(request.granted_by_user_id)
        self.assertFalse(request.approver_ids.filtered("decision_date"))

    # -- a decision on the request moves the leave -------------------------

    def test_approving_the_request_validates_the_leave(self):
        leave = self._leave("manager")

        leave.sudo().approval_request_id.with_user(
            self.user_responsible_id
        ).action_approve()

        self.assertEqual(leave.state, "validate")
        self.assertEqual(leave.first_approver_id, self.employee_responsible)

    def test_the_leave_manager_approving_the_request_moves_to_second_approval(self):
        leave = self._leave("both")

        leave.sudo().approval_request_id.with_user(
            self.user_responsible_id
        ).action_approve()

        self.assertEqual(leave.state, "validate1")
        self.assertEqual(leave.first_approver_id, self.employee_responsible)

    def test_refusing_the_request_refuses_the_leave(self):
        leave = self._leave("hr")

        leave.sudo().approval_request_id.with_user(self.user_hruser_id).with_context(
            skip_wizard=True
        ).action_refuse()

        self.assertEqual(leave.state, "refuse")

    def test_time_off_policy_still_decides_through_the_request(self):
        leave_type = self._leave_type("hr")
        leave_type.responsible_ids = self.user_responsible
        leave = self._leave("hr", leave_type=leave_type)
        request = leave.sudo().approval_request_id
        self.assertIn(self.user_responsible, request.approver_ids.user_id)

        with self.assertRaises(UserError):
            request.with_user(self.user_responsible_id).action_approve()

        self.assertEqual(leave.state, "confirm")
        self.assertEqual(request.state, "pending")

    def test_a_request_cancelled_by_the_engine_cancels_the_leave(self):
        leave = self._leave("manager")

        leave.sudo().approval_request_id._force_terminal("cancelled", "Expired")

        self.assertEqual(leave.state, "cancel")

    # -- the request follows its leave -------------------------------------

    def test_the_request_is_not_moved_from_the_approvals_app(self):
        leave = self._leave("manager")
        request = leave.sudo().approval_request_id
        with self.assertRaises(UserError):
            request.with_user(self.user_employee_id).action_cancel()

        leave.with_user(self.user_responsible_id).action_approve()

        with self.assertRaises(UserError):
            request.with_user(self.user_responsible_id).action_withdraw()
        with self.assertRaises(UserError):
            request.with_user(SUPERUSER_ID).action_reset_to_draft()
        self.assertEqual(request.state, "approved")

    def test_deleting_a_pending_leave_cancels_its_request(self):
        leave = self._leave("manager")
        request = leave.sudo().approval_request_id

        leave.with_user(self.user_employee_id).unlink()

        self.assertEqual(request.state, "cancelled")

    def test_pieces_of_a_pending_leave_raise_their_own_request(self):
        leave = self._leave("manager", days=3)
        request = leave.sudo().approval_request_id

        pieces = leave.sudo()._split_leaves(
            self.leave_day + relativedelta(days=1),
            self.leave_day + relativedelta(days=2),
        )

        self.assertTrue(pieces)
        for piece in pieces:
            self.assertEqual(piece.approval_request_id.state, "pending")
            self.assertNotEqual(piece.approval_request_id, request)
        self.assertEqual(request.state, "pending")

    def test_the_leave_manager_is_asked_on_the_leave(self):
        leave = self._leave("manager")

        activity = leave.sudo().activity_ids
        self.assertRecordValues(
            activity,
            [
                {
                    "user_id": self.user_responsible_id,
                    "activity_type_id": self.env.ref(
                        "hr_holidays.mail_act_leave_approval"
                    ).id,
                    "approver_id": leave.sudo()
                    .approval_request_id.approver_ids.filtered(
                        lambda row: row.user_id == self.user_responsible
                    )
                    .id,
                }
            ],
        )

        leave.with_user(self.user_responsible_id).action_approve()
        self.assertFalse(leave.sudo().activity_ids)

    # -- leaves in flight when time off adopted the engine -------------------

    def test_a_leave_pending_before_the_engine_gets_its_request_and_one_activity(self):
        leave = self._leave("manager", user=SUPERUSER_ID)
        self.assertFalse(leave.approval_request_id)
        legacy_type = self.env.ref("hr_holidays.mail_act_leave_approval")
        self.assertEqual(leave.activity_ids.activity_type_id, legacy_type)
        self.assertFalse(leave.activity_ids.approver_id)

        leave._backfill_approval_requests()

        request = leave.sudo().approval_request_id
        self.assertEqual(request.state, "pending")
        self.assertEqual(request.request_owner_id, self.user_employee)
        self.assertEqual(len(leave.activity_ids), 1)
        self.assertEqual(leave.activity_ids.approver_id.request_id, request)
        self.assertEqual(leave.activity_ids.activity_type_id, legacy_type)

    def test_a_leave_first_approved_before_the_engine_keeps_that_decision(self):
        leave = self._leave("both", user=SUPERUSER_ID)
        leave.write(
            {"state": "validate1", "first_approver_id": self.employee_responsible.id}
        )
        self.assertFalse(leave.approval_request_id)

        leave._backfill_approval_requests()

        request = leave.sudo().approval_request_id
        manager_step = self.env.ref("hr_holidays.approval_category_leave_step_manager")
        officer_step = self.env.ref("hr_holidays.approval_category_leave_step_officer")
        self.assertEqual(request.state, "pending")
        row = request.approver_ids.filtered(
            lambda row: row.user_id == self.user_responsible
        )
        self.assertEqual(row.decided_step_ids, manager_step)
        self.assertEqual(row.decided_by_user_id, self.user_responsible)
        self.assertEqual(request._get_open_steps(), officer_step)
        self.assertEqual(leave.state, "validate1")
        self.assertFalse(
            leave.activity_ids.filtered(lambda activity: not activity.approver_id)
        )
