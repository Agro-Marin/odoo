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
        self.env.ref("approval.approval_category_data_business_trip").write(
            {
                "approver_ids": [
                    (5, 0, 0),
                    (0, 0, {"user_id": self.env.ref("base.user_admin").id}),
                ],
                "approval_minimum": 1,
                "approve_sequentially": False,
            }
        )
        self.start_tour("/odoo", "approvals_tour", login="admin")

    def test_approval_button_tour(self):
        """The button, the popover and approval.binding agree on one contract."""
        admin = self.env.ref("base.user_admin")
        category = self.env["approval.category"].create(
            {"name": "Button Tour", "approval_minimum": 1}
        )
        self.env["approval.category.approver"].create(
            {
                "category_id": category.id,
                "user_id": admin.id,
                "required": True,
                "sequence": 10,
            }
        )
        self.env["ir.ui.view"].create(
            {
                "name": "res.partner.form.approval.button.tour",
                "model": "res.partner",
                "inherit_id": self.env.ref("base.view_partner_form").id,
                "arch": """
                    <xpath expr="//sheet" position="before">
                        <header>
                            <button name="action_archive" type="object" string="Archive"/>
                        </header>
                    </xpath>
                """,
            }
        )
        binding = self.env["approval.binding"].create(
            {
                "model_id": self.env["ir.model"]._get("res.partner").id,
                "method": "action_archive",
                "mode": "request",
                "category_id": category.id,
                "run_on_approval": False,
            }
        )
        self.addCleanup(self.env["approval.binding"]._unregister_hook)
        partner = self.env["res.partner"].create({"name": "Button Tour Partner"})
        self.start_tour(
            f"/odoo/res.partner/{partner.id}", "approval_button_tour", login="admin"
        )
        request = self.env["approval.request"].search(
            [("binding_id", "=", binding.id), ("res_id", "=", partner.id)]
        )
        self.assertEqual(request.state, "approved")
        self.assertTrue(partner.active, "deciding from the button runs nothing")
