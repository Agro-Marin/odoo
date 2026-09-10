from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import tagged

from .common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestApprovalStepDecisions(ApprovalCommon):
    """A decision is given for steps: the ones it names, or every step of the row.

    One row stands for a user on a request, however many step pools they are in, and
    the approval button draws a decide control under each step. Approving under the
    second step must not also approve the first.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        approver_group = cls.env.ref("approval.group_approval_approver")
        cls.approver_3 = cls.env["res.users"].create(
            {
                "name": "Decision Three",
                "login": "decision_u3",
                "email": "decision_u3@test.com",
                "group_ids": [(4, approver_group.id)],
            },
        )
        cls.watcher = cls.env["res.users"].create(
            {
                "name": "Decision Watcher",
                "login": "decision_watcher",
                "email": "decision_watcher@test.com",
                "group_ids": [(4, approver_group.id)],
            },
        )

    def _request_with_steps(self, first_vals=None, second_vals=None):
        category = self._make_category(name=f"Decisions {self.id()}")
        Step = self.env["approval.category.step"]
        self.first = Step.create(
            {
                "category_id": category.id,
                "name": "First",
                "sequence": 10,
                "member_ids": [
                    Command.create({"user_id": user.id})
                    for user in (self.approver_1, self.approver_2)
                ],
                **(first_vals or {}),
            },
        )
        self.second = Step.create(
            {
                "category_id": category.id,
                "name": "Second",
                "sequence": 20,
                "member_ids": [
                    Command.create({"user_id": user.id})
                    for user in (self.approver_1, self.approver_3)
                ],
                **(second_vals or {}),
            },
        )
        request = self._prepare_request(category)
        self.row = request.approver_ids.filtered(
            lambda approver: approver.user_id == self.approver_1
        )
        return request

    def _approval_activity_users(self, request):
        activity_type = self.env.ref("approval.mail_activity_data_approval")
        return request.activity_ids.filtered(
            lambda activity: activity.activity_type_id == activity_type
        ).user_id

    def test_a_decision_naming_a_step_counts_toward_that_step_only(self):
        request = self._request_with_steps()
        request.with_user(self.approver_1).action_approve(steps=self.first)
        self.assertEqual(request.state, "pending")
        self.assertEqual(self.row.decided_step_ids, self.first)
        self.assertEqual(request._get_unmet_steps(), self.second)
        request.with_user(self.approver_1).action_approve(steps=self.second)
        self.assertEqual(request.state, "approved")
        self.assertEqual(self.row.decided_step_ids, self.first | self.second)

    def test_a_decision_naming_no_step_is_given_for_every_step_of_the_row(self):
        request = self._request_with_steps()
        request.with_user(self.approver_1).action_approve()
        self.assertEqual(request.state, "approved")
        self.assertEqual(self.row.decided_step_ids, self.first | self.second)

    def test_who_decided_which_exclusive_step_stays_fixed(self):
        category = self._make_category(name=f"Fixed {self.id()}")
        first, second = (
            self.env["approval.category.step"].create(
                {
                    "category_id": category.id,
                    "name": name,
                    "sequence": 10,
                    "exclusive": True,
                    "member_ids": [
                        Command.create({"user_id": user.id})
                        for user in (self.approver_1, self.approver_2)
                    ],
                },
            )
            for name in ("First", "Second")
        )
        request = self._prepare_request(category)
        sorted_first, sorted_last = request.approver_ids.filtered(
            lambda approver: approver.user_id in (self.approver_1, self.approver_2)
        ).sorted(lambda approver: (approver.sequence, approver.id))
        sorted_last.with_user(sorted_last.user_id).action_approve()
        self.assertEqual(sorted_last.decided_step_ids, first)
        sorted_first.with_user(sorted_first.user_id).action_approve()
        self.assertEqual(sorted_first.decided_step_ids, second)
        self.assertEqual(
            request._get_step_assignment()[first.id],
            sorted_last,
            "an approval keeps its step when a row sorted before it approves later",
        )
        self.assertEqual(request.state, "approved")

    def test_a_consent_approval_counts_toward_every_step(self):
        request = self._request_with_steps()
        request.category_id.consent_approval_hours = 24
        request.date_confirmed = fields.Datetime.now() - timedelta(hours=30)
        self.env["approval.request"].cron_consent_approval()
        self.assertEqual(request.state, "approved")
        self.assertEqual(self.row.decided_step_ids, self.first | self.second)

    def test_a_listed_member_is_asked_once_their_own_step_opens(self):
        """Studio's test_entries_approved_by_other_read_by_regular_user."""
        group = self.env["res.groups"].create({"name": f"Asked {self.id()}"})
        self.approver_3.group_ids = [Command.link(group.id)]
        category = self._make_category(name=f"Asked {self.id()}")
        category.notify_sequentially = True
        Step = self.env["approval.category.step"]
        Step.create(
            {
                "category_id": category.id,
                "name": "First",
                "sequence": 10,
                "group_id": group.id,
                "member_ids": [Command.create({"user_id": self.approver_2.id})],
            },
        )
        Step.create(
            {
                "category_id": category.id,
                "name": "Second",
                "sequence": 20,
                "member_ids": [Command.create({"user_id": self.approver_3.id})],
            },
        )
        request = self._prepare_request(category)
        self.assertEqual(
            self._approval_activity_users(request),
            self.approver_2,
            "the group lets approver_3 decide the first step; they are listed for "
            "the second only",
        )
        request.with_user(self.approver_2).action_approve()
        self.assertEqual(self._approval_activity_users(request), self.approver_3)

    def test_a_decided_step_archived_meanwhile_stays_decided(self):
        request = self._request_with_steps()
        request.with_user(self.approver_1).action_approve(steps=self.first)
        self.first.active = False
        request.with_user(self.approver_1).action_approve(steps=self.second)
        self.first.active = True
        self.assertEqual(
            self.row.decided_step_ids,
            self.first | self.second,
            "deciding the second step while the first was archived kept the first",
        )
        self.assertEqual(request.state, "approved")

    def test_a_step_is_decided_once_per_user(self):
        request = self._request_with_steps()
        request.with_user(self.approver_1).action_approve(steps=self.first)
        with self.assertRaises(UserError):
            request.with_user(self.approver_1).action_approve(steps=self.first)

    def test_a_step_the_user_is_not_in_cannot_be_decided(self):
        request = self._request_with_steps()
        with self.assertRaises(UserError):
            request.with_user(self.approver_2).action_approve(steps=self.second)
        self.assertEqual(request.state, "pending")

    def test_an_exclusive_decided_step_refuses_a_second_one(self):
        request = self._request_with_steps(first_vals={"exclusive": True})
        request.with_user(self.approver_1).action_approve(steps=self.first)
        with self.assertRaises(UserError):
            request.with_user(self.approver_1).action_approve(steps=self.second)
        self.assertEqual(self.row.decided_step_ids, self.first)

    def test_an_exclusive_step_is_refused_after_another_decided_step(self):
        request = self._request_with_steps(second_vals={"exclusive": True})
        request.with_user(self.approver_1).action_approve(steps=self.first)
        with self.assertRaises(UserError):
            request.with_user(self.approver_1).action_approve(steps=self.second)

    def test_withdrawing_one_step_keeps_the_other_and_asks_again(self):
        request = self._request_with_steps()
        request.with_user(self.approver_1).action_approve(steps=self.first)
        request.with_user(self.approver_1).action_approve(steps=self.second)
        self.assertEqual(request.state, "approved")
        request.with_user(self.approver_1).action_withdraw_approver(
            self.row.id, self.second.id
        )
        self.assertEqual(request.state, "pending")
        self.assertEqual(self.row.state, "approved")
        self.assertEqual(self.row.decided_step_ids, self.first)
        waiting = request.approver_ids.filtered(
            lambda approver: approver.user_id == self.approver_3
        )
        self.assertEqual(
            waiting.state, "pending", "the step it reopened is asked again"
        )
        self.assertIn(self.approver_3, self._approval_activity_users(request))

    def test_withdrawing_the_only_decided_step_withdraws_the_decision(self):
        request = self._request_with_steps()
        request.with_user(self.approver_1).action_approve(steps=self.first)
        request.with_user(self.approver_1).action_withdraw_approver(
            self.row.id, self.first.id
        )
        self.assertEqual(self.row.state, "pending")
        self.assertFalse(self.row.decided_step_ids)
        self.assertFalse(self.row.decided_by_user_id)

    def test_a_step_the_decision_was_not_given_for_cannot_be_withdrawn(self):
        request = self._request_with_steps()
        request.with_user(self.approver_1).action_approve(steps=self.first)
        with self.assertRaises(UserError):
            request.with_user(self.approver_1).action_withdraw_approver(
                self.row.id, self.second.id
            )

    def test_a_refusal_naming_a_step_refuses_the_request(self):
        request = self._request_with_steps()
        request.with_user(self.approver_1).action_approve(steps=self.first)
        request.with_user(self.approver_1).with_context(skip_wizard=True).action_refuse(
            steps=self.second
        )
        self.assertEqual(request.state, "refused")
        self.assertEqual(self.row.state, "refused")
        self.assertEqual(self.row.decided_step_ids, self.second)

    def test_a_reset_clears_the_decided_steps(self):
        request = self._request_with_steps()
        request.with_user(self.approver_1).action_approve(steps=self.first)
        request.with_user(self.approver_1).action_approve(steps=self.second)
        self.assertEqual(request.state, "approved")
        request.action_reset_to_draft()
        self.assertFalse(request.approver_ids.decided_step_ids)

    def test_the_note_names_the_steps_the_decision_counts_toward(self):
        request = self._request_with_steps(
            first_vals={
                "exclusive": True,
                "notify_user_ids": [Command.set(self.watcher.ids)],
            },
            second_vals={"notify_user_ids": [Command.set(self.watcher.ids)]},
        )
        request.with_user(self.approver_1).action_approve()
        note = request.message_ids.filtered(
            lambda message: self.watcher.partner_id in message.partner_ids
        )
        self.assertEqual(len(note), 1)
        self.assertIn("First", note.body)
        self.assertNotIn("Second", note.body)
