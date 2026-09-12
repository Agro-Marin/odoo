from odoo.tests import tagged

from odoo.addons.approval.tests.common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestPerformanceViewAttribution(ApprovalCommon):
    def test_performance_view_credits_the_delegate(self):
        category = self._make_category(
            "Attribution Perf",
            approvers=[(self.approver_1, True, 10)],
        )
        request = self._prepare_request(category)
        row = request.approver_ids[0]
        self._delegate_row(row, self.approver_2)
        request.with_user(self.approver_2).action_approve()
        self.env.flush_all()

        rows = (
            self.env["approver.performance"]
            .sudo()
            .search_read(
                [("user_id", "in", (self.approver_1 | self.approver_2).ids)],
                ["user_id", "total_approvals"],
            )
        )
        credited = {r["user_id"][0]: r["total_approvals"] for r in rows}
        self.assertEqual(
            credited.get(self.approver_2.id),
            1,
            "the delegate who decided must be credited",
        )
        self.assertNotIn(
            self.approver_1.id,
            credited,
            "the principal, who did nothing, must not be credited",
        )
