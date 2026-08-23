from lxml import etree

from odoo.tests import tagged

from .common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestPrintButtonVisibility(ApprovalCommon):
    def test_print_button_invisible_condition_no_longer_gates_on_approval_type(self):
        view = self.env.ref("approval.view_approval_request_form")
        arch = etree.fromstring(view.arch)
        buttons = arch.xpath(
            '//button[@name="%d"]'
            % self.env.ref("approval.action_report_approval_request").id
        )
        self.assertTrue(buttons, "Print button not found in the form arch")
        invisible = buttons[0].get("invisible", "")
        self.assertNotIn(
            "approval_type",
            invisible,
            "the Print button's invisible condition must not reference "
            "approval_type any more — it only gates on state == 'approved'",
        )

    def test_print_report_binding_is_generic_for_any_approval_type(self):
        report = self.env.ref("approval.action_report_approval_request")
        self.assertEqual(report.binding_type, "report")
        self.assertEqual(report.binding_model_id.model, "approval.request")

    def test_approval_product_report_template_extension_unaffected(self):
        module = (
            self.env["ir.module.module"]
            .sudo()
            .search([("name", "=", "approval_product"), ("state", "=", "installed")])
        )
        if not module:
            self.skipTest("approval_product not installed")
        extension = self.env.ref(
            "approval_product.report_approval_request_document_products"
        )
        self.assertEqual(
            extension.inherit_id,
            self.env.ref("approval.report_approval_request_document"),
        )

    def test_general_type_request_reaches_approved_state(self):
        category = self._make_category(
            name=f"Print Button Cat {self.id()}",
            approvers=[self.approver_1],
            approval_type="general",
        )
        request = self._prepare_request(category)
        request.with_user(self.approver_1).action_approve()
        self.assertEqual(request.state, "approved")
        self.assertEqual(request.approval_type, "general")
