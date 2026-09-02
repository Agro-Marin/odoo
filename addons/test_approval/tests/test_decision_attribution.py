from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from odoo.addons.approval.tests.common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestDecisionAttribution(ApprovalCommon):
    def _document_for(self, category):
        partner = self.env["res.partner"].create({"name": "A4 doc partner"})
        document = self.env["approval.test.document"].create(
            {
                "name": "A4 doc",
                "partner_id": partner.id,
                "test_category_id": category.id,
            },
        )
        request = self._prepare_request(
            category,
            confirm=False,
            res_model="approval.test.document",
            res_id=document.id,
        )
        document.approval_request_id = request.id
        return document, request

    def test_decider_names_credit_the_delegate_who_actually_decided(self):
        category = self._make_category(
            "A4 attribution", approvers=[(self.approver_1, True, 10)]
        )
        document, request = self._document_for(category)
        today = fields.Date.today()
        request.approver_ids.sudo().write(
            {
                "delegate_id": self.approver_2.id,
                "delegate_start_date": today,
                "delegate_end_date": today + timedelta(days=5),
            },
        )
        request.action_confirm()
        request.with_user(self.approver_2).with_context(
            skip_wizard=True,
        ).action_approve()

        self.assertEqual(
            document._approval_decider_names(),
            self.approver_2.name,
            "the source document must name the delegate who exercised the "
            "approval, not the principal whose slot it was — decided_by_"
            "user_id exists precisely to answer this",
        )

    def test_decider_names_ignore_rows_nobody_decided(self):
        category = self._make_category(
            "A4 consent",
            approvers=[(self.approver_1, True, 10)],
            consent_approval_hours=1,
        )
        document, request = self._document_for(category)
        request.action_confirm()
        request.sudo().write(
            {"date_confirmed": fields.Datetime.now() - timedelta(hours=5)},
        )
        self.env["approval.request"].cron_consent_approval()

        self.assertEqual(request.state, "approved")
        self.assertEqual(
            document._approval_decider_names(),
            "",
            "consent auto-approval is not a decision: no approver may be "
            "named as having approved",
        )
