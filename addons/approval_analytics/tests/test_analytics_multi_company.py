from odoo.tests import tagged

from odoo.addons.approval.tests.test_multi_company import MultiCompanyCase


@tagged("post_install", "-at_install")
class TestAnalyticsMultiCompany(MultiCompanyCase):
    def test_metrics_view_isolated_across_companies(self):
        found = (
            self.env["approval.metrics"]
            .with_user(self.user_a)
            .search([("category_id", "=", self.category_b.id)])
        )
        self.assertFalse(
            found,
            "Company A manager must not see Company B's approval metrics",
        )
        found_b = (
            self.env["approval.metrics"]
            .with_user(self.user_b)
            .search([("category_id", "=", self.category_b.id)])
        )
        self.assertTrue(found_b, "Company B manager should see its own metrics")

    def test_approver_performance_view_isolated_across_companies(self):
        found = (
            self.env["approver.performance"]
            .with_user(self.user_a)
            .search([("user_id", "=", self.approver_b.id)])
        )
        self.assertFalse(
            found,
            "Company A manager must not see Company B's approver performance data",
        )
        found_b = (
            self.env["approver.performance"]
            .with_user(self.user_b)
            .search([("user_id", "=", self.approver_b.id)])
        )
        self.assertTrue(found_b)
