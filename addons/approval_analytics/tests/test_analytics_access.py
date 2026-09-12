from odoo.exceptions import AccessError
from odoo.tests import tagged

from odoo.addons.approval.tests.common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestReportModelAccess(ApprovalCommon):
    def test_reports_not_readable_by_plain_user(self):
        for model in ("approval.dashboard", "approval.metrics", "approver.performance"):
            with self.assertRaises(
                AccessError,
                msg=f"{model} must not be readable by a non-manager user",
            ):
                self.env[model].with_user(self.owner_user).search([])

    def test_reports_readable_by_manager(self):
        for model in ("approval.dashboard", "approval.metrics", "approver.performance"):
            self.env[model].with_user(self.manager_user).search([])
