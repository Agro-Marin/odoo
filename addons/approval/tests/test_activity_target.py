from odoo.fields import Command
from odoo.tests import tagged

from .common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestActivityTarget(ApprovalCommon):
    """A category chooses where its approvers are asked, and a step with which activity.

    Time off asks its approvers on the leave, with its own activity types, and its
    dashboards read those. Asked on the request instead, every approver would get a
    second activity for the same decision.
    """

    def _category(self, **vals):
        return self._make_category(
            name=f"Target {self.id()}", approvers=[self.approver_1], **vals
        )

    def _request_on_partner(self, category):
        return self._prepare_request(
            category, res_model="res.partner", res_id=self.partner.id
        )

    def _approval_activities(self, request):
        return self.env["mail.activity"].search(
            [("approver_id.request_id", "=", request.id)]
        )

    def test_a_category_can_ask_on_the_document(self):
        request = self._request_on_partner(self._category(activity_target="document"))

        activity = self._approval_activities(request)

        self.assertEqual(len(activity), 1)
        self.assertEqual(activity.res_model, "res.partner")
        self.assertEqual(activity.res_id, self.partner.id)
        self.assertEqual(activity.user_id, self.approver_1)
        self.assertEqual(activity.approver_id, request.approver_ids)

    def test_the_default_still_asks_on_the_request(self):
        request = self._request_on_partner(self._category())

        self.assertEqual(
            self._approval_activities(request).res_model, "approval.request"
        )

    def test_a_document_activity_marked_done_approves(self):
        request = self._request_on_partner(self._category(activity_target="document"))

        self._approval_activities(request).with_user(self.approver_1).action_done()

        self.assertEqual(request.state, "approved")

    def test_a_request_without_a_document_asks_on_itself(self):
        request = self._prepare_request(self._category(activity_target="document"))

        self.assertEqual(
            self._approval_activities(request).res_model, "approval.request"
        )

    def test_a_step_chooses_the_activity_type(self):
        todo = self.env.ref("mail.mail_activity_data_todo")
        category = self._make_category(
            name=f"Target step {self.id()}", activity_target="document"
        )
        self.env["approval.category.step"].create(
            {
                "category_id": category.id,
                "name": "Typed",
                "member_ids": [Command.create({"user_id": self.approver_1.id})],
                "activity_type_id": todo.id,
            }
        )

        request = self._request_on_partner(category)

        self.assertEqual(self._approval_activities(request).activity_type_id, todo)

    def test_asking_again_does_not_duplicate_a_document_activity(self):
        request = self._request_on_partner(self._category(activity_target="document"))

        request.approver_ids._create_activity()

        self.assertEqual(len(self._approval_activities(request)), 1)

    def test_cancelling_removes_the_document_activity(self):
        request = self._request_on_partner(self._category(activity_target="document"))
        activity = self._approval_activities(request)

        request.action_cancel()

        self.assertFalse(activity.exists())

    def test_a_reminder_refreshes_the_document_activity(self):
        request = self._request_on_partner(self._category(activity_target="document"))

        request._send_reminder()

        activities = self._approval_activities(request)
        self.assertEqual(len(activities), 1)
        self.assertEqual(activities.res_model, "res.partner")
        self.assertFalse(
            request.activity_ids.filtered(lambda a: a.user_id == self.approver_1)
        )
