from odoo import SUPERUSER_ID
from odoo.exceptions import UserError, ValidationError
from odoo.tests import new_test_user, tagged

from odoo.addons.hr_expense.tests.common import TestExpenseCommon


@tagged("post_install", "-at_install")
class TestExpenseApprovalEngine(TestExpenseCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category = cls.env.ref("hr_expense.approval_category_expense")

    def _expense(self, user=None, **vals):
        model = (
            self.env["hr.expense"]
            .with_user(user or self.expense_user_employee)
            .with_company(self.env.company)
        )
        return model.create(
            {
                "name": "Engine expense",
                "employee_id": self.expense_employee.id,
                "product_id": self.product_c.id,
                "total_amount_currency": 100.0,
                **vals,
            }
        )

    def _submitted(self, **vals):
        expense = self._expense(**vals)
        expense.with_user(self.expense_user_employee).action_submit()
        return expense

    def _row(self, request, user):
        return request.approver_ids.filtered(lambda row: row.user_id == user)

    # -- the request a submission raises ------------------------------------

    def test_a_submission_raises_a_pending_request_asking_the_manager(self):
        expense = self._submitted()

        self.assertEqual(expense.review_state, "submitted")
        request = expense.sudo().approval_request_id
        self.assertEqual(request.state, "pending")
        self.assertEqual(request.category_id, self.category)
        self.assertEqual(request.request_owner_id, self.expense_user_employee)
        self.assertEqual(request.amount, 100.0)
        self.assertIn(self.expense_user_manager, request.approver_ids.user_id)
        self.assertRecordValues(
            expense.sudo().activity_ids,
            [
                {
                    "user_id": self.expense_user_manager.id,
                    "activity_type_id": self.env.ref(
                        "hr_expense.mail_act_expense_approval"
                    ).id,
                }
            ],
        )

    def test_an_autovalidated_expense_raises_no_request(self):
        self.expense_employee.sudo().expense_manager_id = False
        expense = self._expense(manager_id=False)

        expense.with_user(self.expense_user_employee).action_submit()

        self.assertEqual(expense.review_state, "approved")
        self.assertFalse(expense.sudo().approval_request_id)

    def test_the_superuser_submits_without_a_request(self):
        expense = self._expense(user=SUPERUSER_ID)

        expense.with_user(SUPERUSER_ID).with_company(self.env.company).action_submit()

        self.assertEqual(expense.review_state, "submitted")
        self.assertFalse(expense.approval_request_id)

    # -- who holds a row -------------------------------------------------------

    def test_only_users_the_expense_policy_lets_approve_hold_a_row(self):
        team_approver = new_test_user(
            self.env,
            login="engine_team_approver",
            groups="base.group_user,hr_expense.group_hr_expense_team_approver",
        )
        all_approver = new_test_user(
            self.env,
            login="engine_all_approver",
            groups="base.group_user,hr_expense.group_hr_expense_user",
        )

        expense = self._submitted()

        users = expense.sudo().approval_request_id.approver_ids.user_id
        self.assertIn(self.expense_user_manager, users)
        self.assertIn(all_approver, users)
        self.assertNotIn(team_approver, users)
        self.assertNotIn(self.expense_user_employee, users)

    def test_an_approver_holds_no_row_on_their_own_expense(self):
        all_approver = new_test_user(
            self.env,
            login="engine_own_approver",
            groups="base.group_user,hr_expense.group_hr_expense_user",
        )
        employee = (
            self.env["hr.employee"]
            .sudo()
            .create(
                {
                    "name": "Engine approving employee",
                    "user_id": all_approver.id,
                    "expense_manager_id": self.expense_user_manager.id,
                }
            )
        )
        expense = self._expense(user=all_approver, employee_id=employee.id)

        expense.with_user(all_approver).action_submit()

        users = expense.sudo().approval_request_id.approver_ids.user_id
        self.assertIn(self.expense_user_manager, users)
        self.assertNotIn(all_approver, users)

    def test_a_manager_submitting_leaves_the_employee_the_request_owner(self):
        expense = self._expense()

        expense.with_user(self.expense_user_manager).action_submit()

        request = expense.sudo().approval_request_id
        self.assertEqual(request.state, "pending")
        self.assertEqual(request.request_owner_id, self.expense_user_employee)

    def _approver_who_loses_the_right(self):
        all_approver = new_test_user(
            self.env,
            login="engine_demoted_approver",
            groups="base.group_user,hr_expense.group_hr_expense_user",
        )
        expense = self._submitted()
        request = expense.sudo().approval_request_id
        self.assertIn(all_approver, request.approver_ids.user_id)
        all_approver.sudo().group_ids = [
            (3, self.env.ref("hr_expense.group_hr_expense_user").id)
        ]
        return all_approver, expense, request

    def test_an_approver_who_lost_the_right_cannot_approve_from_the_request(self):
        all_approver, expense, request = self._approver_who_loses_the_right()

        with self.assertRaises(UserError):
            request.with_user(all_approver).action_approve()

        self.assertEqual(expense.review_state, "submitted")
        self.assertEqual(request.state, "pending")

    def test_an_approver_who_lost_the_right_cannot_refuse_from_the_request(self):
        all_approver, expense, request = self._approver_who_loses_the_right()

        with self.assertRaises(UserError):
            request.with_user(all_approver).with_context(
                skip_wizard=True
            ).action_refuse()

        self.assertEqual(expense.review_state, "submitted")
        self.assertEqual(request.state, "pending")

    # -- decisions taken through the expense ----------------------------------

    def test_the_manager_approving_records_their_decision(self):
        expense = self._submitted()

        expense.with_user(self.expense_user_manager).action_approve()

        self.assertEqual(expense.review_state, "approved")
        self.assertTrue(expense.approval_date)
        request = expense.sudo().approval_request_id
        self.assertEqual(request.state, "approved")
        self.assertEqual(
            self._row(request, self.expense_user_manager).decided_by_user_id,
            self.expense_user_manager,
        )
        self.assertFalse(expense.sudo().activity_ids)

    def test_the_manager_refusing_records_their_decision_and_reason(self):
        expense = self._submitted()

        expense.with_user(self.expense_user_manager)._do_refuse("Not a business cost")

        self.assertEqual(expense.review_state, "refused")
        request = expense.sudo().approval_request_id
        self.assertEqual(request.state, "refused")
        self.assertEqual(request.refusal_note, "Not a business cost")
        self.assertEqual(
            self._row(request, self.expense_user_manager).decided_by_user_id,
            self.expense_user_manager,
        )

    def test_refusing_an_approved_expense_revokes_its_request(self):
        expense = self._submitted()
        expense.with_user(self.expense_user_manager).action_approve()

        expense.with_user(self.expense_user_manager_2)._do_refuse("Duplicate")

        request = expense.sudo().approval_request_id
        self.assertEqual(request.state, "refused")
        self.assertEqual(request.revoked_state, "refused")
        self.assertEqual(request.refusal_note, "Duplicate")

    def test_a_reset_expense_resets_its_request_and_resubmitting_restarts_it(self):
        expense = self._submitted()
        expense.with_user(self.expense_user_manager).action_approve()

        expense.with_user(self.expense_user_manager).action_reset()
        request = expense.sudo().approval_request_id
        self.assertEqual(request.state, "new")

        expense.with_user(self.expense_user_employee).action_submit()
        self.assertEqual(request.state, "pending")
        self.assertFalse(request.approver_ids.filtered("decision_date"))

    # -- decisions taken on the request ---------------------------------------

    def test_approving_the_request_approves_the_expense(self):
        expense = self._submitted()

        expense.sudo().approval_request_id.with_user(
            self.expense_user_manager
        ).action_approve()

        self.assertEqual(expense.review_state, "approved")
        self.assertEqual(expense.manager_id, self.expense_user_manager)

    def test_refusing_the_request_gives_the_expense_its_reason(self):
        expense = self._submitted()
        request = expense.sudo().approval_request_id
        reason = (
            self.env["approval.refusal.reason"].sudo().create({"name": "Unsupported"})
        )
        wizard = (
            self.env["approval.decision.wizard"]
            .with_user(self.expense_user_manager)
            .create(
                {
                    "approver_id": self._row(request, self.expense_user_manager).id,
                    "decision_type": "refuse",
                    "refusal_reason_id": reason.id,
                    "note": "No receipt attached",
                }
            )
        )

        wizard.action_confirm_refuse()

        self.assertEqual(expense.review_state, "refused")
        self.assertEqual(request.refusal_note, "No receipt attached")
        self.assertIn("No receipt attached", str(expense.message_ids.mapped("body")))

    def test_a_possible_duplicate_is_approved_from_the_expense_only(self):
        expense = self._submitted()
        self._submitted()
        request = expense.sudo().approval_request_id

        with self.assertRaises(UserError) as caught:
            request.with_user(self.expense_user_manager).action_approve()

        self.assertIn("may duplicate", str(caught.exception))
        self.assertEqual(expense.review_state, "submitted")
        self.assertEqual(request.state, "pending")

    def test_a_mandatory_analytic_plan_holds_an_approval_from_the_request(self):
        self.env["account.analytic.applicability"].sudo().create(
            {
                "business_domain": "expense",
                "analytic_plan_id": self.analytic_plan.id,
                "applicability": "mandatory",
                "product_categ_id": self.product_c.categ_id.id,
            }
        )
        expense = self._submitted()
        request = expense.sudo().approval_request_id

        with self.assertRaises(ValidationError):
            request.with_user(self.expense_user_manager).action_approve()

        self.assertEqual(expense.review_state, "submitted")
        self.assertEqual(request.state, "pending")

    def test_a_first_of_two_steps_leaves_the_expense_submitted(self):
        self.env["approval.category.step"].sudo().create(
            {
                "category_id": self.category.id,
                "name": "Finance",
                "sequence": 20,
                "minimum": 1,
                "user_ids": [(6, 0, self.expense_user_manager_2.ids)],
            }
        )
        expense = self._submitted()
        request = expense.sudo().approval_request_id

        request.with_user(self.expense_user_manager).action_approve(
            approver=self._row(request, self.expense_user_manager)
        )

        self.assertEqual(request.state, "pending")
        self.assertEqual(expense.review_state, "submitted")

        request.with_user(self.expense_user_manager_2).action_approve()

        self.assertEqual(request.state, "approved")
        self.assertEqual(expense.review_state, "approved")

    def test_a_request_cancelled_by_the_engine_refuses_the_expense(self):
        expense = self._submitted()

        expense.sudo().approval_request_id._force_terminal("cancelled", "Expired")

        self.assertEqual(expense.review_state, "refused")

    # -- the request follows its expense --------------------------------------

    def test_deleting_a_submitted_expense_cancels_its_request(self):
        expense = self._submitted()
        request = expense.sudo().approval_request_id

        expense.with_user(self.expense_user_manager).unlink()

        self.assertEqual(request.state, "cancelled")
