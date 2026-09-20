from datetime import timedelta

from odoo.tests import tagged

from odoo.addons.approval.tests.common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestSLAMetricsAgreement(ApprovalCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category = cls._make_category(
            name="SLA Metrics Agreement",
            approvers=[(cls.approver_1, False, 10)],
            sla_target_hours=10,
        )

    def test_view_compliance_matches_the_record_status(self):
        inside, outside = 3, 3
        for hours in ([2] * inside) + ([40] * outside):
            request = self._prepare_request(self.category)
            request.with_user(self.approver_1).with_context(
                skip_wizard=True,
            ).action_approve()
            self.env.flush_all()
            self.env.cr.execute(
                "UPDATE approval_request SET date_confirmed = %s WHERE id = %s",
                (request.date_approval_granted - timedelta(hours=hours), request.id),
            )
        self.env.invalidate_all()

        approved = self.env["approval.request"].search(
            [("category_id", "=", self.category.id), ("state", "=", "approved")],
        )
        met = approved.filtered(lambda r: r.sla_status == "met")

        rows = (
            self.env["approval.metrics"]
            .sudo()
            .search_read(
                [("category_id", "=", self.category.id)],
                ["sla_compliant_count"],
            )
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["sla_compliant_count"],
            len(met),
            "approval.metrics counts a different set of requests as "
            "SLA-compliant than sla_status does.",
        )
        self.assertEqual(len(met), inside)
