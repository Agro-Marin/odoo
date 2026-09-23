import json

from odoo.tests import HttpCase, new_test_user, tagged

from odoo.addons.approval.tests.common import add_category_approver


@tagged("post_install", "-at_install")
class TestReportDoorContext(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.requester = new_test_user(
            cls.env,
            login="report_door_requester",
            groups="base.group_user,base.group_partner_manager",
        )
        approver = new_test_user(
            cls.env, login="report_door_approver", groups="base.group_user"
        )
        category = cls.env["approval.category"].create(
            {"name": "Report Door Category", "approval_minimum": 1}
        )
        add_category_approver(category, approver, required=True, sequence=10)
        cls.env["ir.ui.view"].create(
            {
                "name": "approval_report_door_probe",
                "type": "qweb",
                "key": "approval.report_door_probe",
                "arch": '<t t-name="approval.report_door_probe">'
                '<t t-foreach="docs" t-as="doc"><span t-out="doc.name"/></t></t>',
            }
        )
        report = cls.env["ir.actions.report"].create(
            {
                "name": "Report door probe",
                "model": "res.partner",
                "report_type": "qweb-html",
                "report_name": "approval.report_door_probe",
            }
        )
        cls.env["approval.binding"].create(
            {
                "model_id": cls.env["ir.model"]._get("res.partner").id,
                "action_id": report.id,
                "category_id": category.id,
                "mode": "block",
                "sudo_policy": "enforce",
            }
        )
        cls.partner = cls.env["res.partner"].create({"name": "Unapproved Printout"})

    @classmethod
    def tearDownClass(cls):
        cls.env["approval.binding"]._unregister_hook()
        super().tearDownClass()

    def _render(self, context=None):
        self.authenticate("report_door_requester", "report_door_requester")
        url = f"/report/html/approval.report_door_probe/{self.partner.id}"
        if context is not None:
            url += "?context=" + json.dumps(context)
        return self.url_open(url)

    def test_the_report_route_refuses_an_uncovered_record(self):
        response = self._render()
        self.assertEqual(response.status_code, 422)
        self.assertIn("Report door probe", response.text)
        self.assertNotIn("<span>Unapproved Printout</span>", response.text)

    def test_a_context_sent_to_the_report_route_does_not_pass_the_gate(self):
        response = self._render({"approval_report_gated": True})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("<span>Unapproved Printout</span>", response.text)
