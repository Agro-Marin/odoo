from odoo import fields
from odoo.tests import tagged

from .common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestActivityLink(ApprovalCommon):
    """An approval activity knows its approver row by a stored link.

    The row was inferred from the activity's model and type, which only an activity
    on the request itself satisfies. Time off asks its approvers on the leave, and an
    activity there must still approve when done and still be cleaned up.
    """

    def _pending_request_on_partner(self):
        category = self._make_category(
            name=f"Activity link {self.id()}", approvers=[self.approver_1]
        )
        return self._prepare_request(
            category, res_model="res.partner", res_id=self.partner.id
        )

    def _activity_on_partner(self, request):
        row = request.approver_ids
        return self.env["mail.activity"].create(
            {
                "activity_type_id": self.env.ref(
                    "approval.mail_activity_data_approval"
                ).id,
                "res_model_id": self.env["ir.model"]._get_id("res.partner"),
                "res_id": self.partner.id,
                "user_id": row.user_id.id,
                "approver_id": row.id,
            }
        )

    def test_an_engine_activity_stores_its_approver_row(self):
        request = self._pending_request_on_partner()
        activity = request.activity_ids.filtered(lambda a: a.user_id == self.approver_1)

        activity.invalidate_recordset(["approver_id"])

        self.assertEqual(activity.approver_id, request.approver_ids)
        self.assertEqual(activity.approval_request_id, request)

    def test_an_approval_activity_on_the_document_approves_when_done(self):
        request = self._pending_request_on_partner()
        activity = self._activity_on_partner(request)

        activity.with_user(self.approver_1).action_done()

        self.assertEqual(request.approver_ids.state, "approved")
        self.assertEqual(request.state, "approved")

    def test_an_approval_activity_on_the_document_goes_with_its_request(self):
        request = self._pending_request_on_partner()
        activity = self._activity_on_partner(request)

        request.action_cancel()

        self.assertFalse(activity.exists())

    def test_a_delegator_marking_their_old_activity_done_decides_nothing(self):
        request = self._pending_request_on_partner()
        row = request.approver_ids
        activity = request.activity_ids.filtered(lambda a: a.user_id == self.approver_1)
        today = fields.Date.context_today(row)
        row.with_user(self.approver_1).write(
            {
                "delegate_id": self.approver_2.id,
                "delegate_start_date": today,
                "delegate_end_date": today,
            }
        )

        activity.with_user(self.approver_1).action_done()

        self.assertEqual(row.state, "pending")
        self.assertEqual(request.state, "pending")
