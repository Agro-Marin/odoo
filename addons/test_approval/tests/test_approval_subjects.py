from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.approval.tests.common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestApprovalSubjects(ApprovalCommon):
    """A record holding one approval request per subject.

    A course holds a request for each partner asking to join it, an engineering change
    one for each stage it passes: several requests live on one record, each told apart
    by its subject_key, and a decision tells the record which subject it decided.
    """

    def _category(self, approvers=None, suffix=""):
        return self._make_category(
            name=f"Subjects {self.id()} {suffix}",
            approvers=[self.approver_1] if approvers is None else approvers,
            company_id=False,
        )

    def _record(self, category=None, **vals):
        return self.env["approval.test.subject.document"].create(
            {
                "name": f"Subjects {self.id()}",
                "test_category_id": (category or self._category()).id,
                **vals,
            }
        )

    def _step(self, category, sequence, **vals):
        return self.env["approval.category.step"].create(
            {
                "category_id": category.id,
                "name": f"Step {sequence}",
                "sequence": sequence,
                "minimum": 1,
                **vals,
            }
        )

    def test_each_subject_raises_its_own_request(self):
        record = self._record()

        first = record._raise_approval_request("access:1")
        second = record._raise_approval_request("access:2")

        self.assertNotEqual(first, second)
        self.assertEqual((first | second).mapped("state"), ["pending", "pending"])
        self.assertEqual(record.approval_request_ids, first | second)
        self.assertEqual(record._get_live_approval_request("access:1"), first)
        self.assertEqual(record._get_live_approval_request("access:2"), second)

    def test_a_subject_holds_one_waiting_request(self):
        record = self._record()
        record._raise_approval_request("access:1")

        with self.assertRaises(UserError):
            record._raise_approval_request("access:1")

    def test_a_decided_subject_can_be_asked_again(self):
        record = self._record()
        first = record._raise_approval_request("access:1")
        first.with_user(self.approver_1).action_approve()
        self.assertFalse(record._get_live_approval_request("access:1"))

        second = record._raise_approval_request("access:1")

        self.assertEqual(second.state, "pending")
        self.assertEqual(record._get_approval_request("access:1"), second)
        self.assertEqual(first.state, "approved")

    def test_a_decision_tells_the_record_which_subject_it_decided(self):
        record = self._record()
        first = record._raise_approval_request("access:1")
        second = record._raise_approval_request("access:2")

        second.with_user(self.approver_1).action_approve()
        self.assertEqual(record.outcomes, "access:2:approved;")

        first.with_user(self.approver_1).with_context(skip_wizard=True).action_refuse()
        self.assertEqual(record.outcomes, "access:2:approved;access:1:refused;")

    def test_a_first_step_tells_the_record_of_progress_on_its_subject(self):
        category = self._category(approvers=[], suffix="steps")
        self._step(category, 10, user_ids=[(6, 0, self.approver_1.ids)])
        self._step(category, 20, user_ids=[(6, 0, self.approver_2.ids)])
        record = self._record(category)
        request = record._raise_approval_request("stage:7")

        request.with_user(self.approver_1).action_approve()

        self.assertEqual(request.state, "pending")
        self.assertEqual(record.outcomes, "stage:7:progress;")

    def test_a_request_without_a_subject_does_not_reach_the_record(self):
        record = self._record()
        request = self.env["approval.request"].create(
            {
                "name": "No subject",
                "category_id": record.test_category_id.id,
                "request_owner_id": self.owner_user.id,
                "res_model": record._name,
                "res_id": record.id,
            }
        )
        request.action_confirm()

        request.with_user(self.approver_1).action_approve()

        self.assertEqual(request.state, "approved")
        self.assertEqual(record.outcomes, "")
        self.assertNotIn(request, record.approval_request_ids)

    def test_the_record_narrows_its_steps_and_chooses_the_activity(self):
        category = self._category(approvers=[], suffix="policy")
        self._step(
            category, 10, group_id=self.env.ref("approval.group_approval_approver").id
        )
        call = self.env.ref("mail.mail_activity_data_call")
        record = self._record(
            category,
            blocked_user_ids=[(6, 0, self.approver_2.ids)],
            asking_activity_type_id=call.id,
        )

        request = record._raise_approval_request("access:1")

        users = request.approver_ids.user_id
        self.assertIn(self.approver_1, users)
        self.assertNotIn(self.approver_2, users)
        row = request.approver_ids.filtered(lambda row: row.user_id == self.approver_1)
        self.assertEqual(row._get_activity_type(), call)

    def test_the_record_adds_its_values_to_the_activity_asked_on_it(self):
        category = self._category(suffix="asked on the record")
        category.activity_target = "document"
        record = self._record(category)

        request = record._raise_approval_request("access:5")

        activity = record.activity_ids.filtered(
            lambda activity: activity.approver_id.request_id == request
        )
        self.assertEqual(activity.user_id, self.approver_1)
        self.assertEqual(activity.summary, "Asked about access:5")

    def test_an_activity_on_the_request_carries_no_record_values(self):
        record = self._record()

        request = record._raise_approval_request("access:5")

        activity = request._get_approval_activities()
        self.assertTrue(activity)
        self.assertNotEqual(activity.summary, "Asked about access:5")
