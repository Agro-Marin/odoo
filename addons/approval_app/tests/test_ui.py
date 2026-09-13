from odoo.tests import tagged

from odoo.addons.base.tests.common import HttpCaseWithUserDemo


@tagged("-at_install", "post_install")
class TestUi(HttpCaseWithUserDemo):
    def test_ui(self):
        self.env.ref("base.user_admin").write(
            {
                "email": "mitchell.admin@example.com",
            }
        )
        category = self.env.ref("approval_app.approval_category_data_business_trip")
        admin = self.env.ref("base.user_admin")
        if not category.step_ids:
            category.write(
                {
                    "approver_ids": [(5, 0, 0)],
                    "approval_minimum": 1,
                    "approve_sequentially": False,
                }
            )
        category.allow_self_approval = True
        if admin not in (category.approver_ids.user_id | category.step_ids.user_ids):
            category._add_approver(admin)
        self.start_tour("/odoo", "approvals_tour", login="admin")
