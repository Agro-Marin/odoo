from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.sale_project.tests.common import TestSaleProjectCommon


@tagged("post_install", "-at_install")
class TestServiceProductConfig(TestSaleProjectCommon):
    def test_onchange_tracking_no_clears_project_and_template(self):
        product = self.env["product.product"].new(
            {
                "name": "svc",
                "type": "service",
                "service_tracking": "no",
                "project_id": self.project_global.id,
                "project_template_id": self.project_template.id,
            }
        )
        product._onchange_service_tracking()
        self.assertFalse(product.project_id)
        self.assertFalse(product.project_template_id)

    def test_onchange_tracking_global_task_clears_template(self):
        product = self.env["product.product"].new(
            {
                "name": "svc",
                "type": "service",
                "service_tracking": "task_global_project",
                "project_id": self.project_global.id,
                "project_template_id": self.project_template.id,
            }
        )
        product._onchange_service_tracking()
        self.assertEqual(product.project_id.id, self.project_global.id)
        self.assertFalse(product.project_template_id)

    def test_onchange_tracking_new_project_clears_project(self):
        product = self.env["product.product"].new(
            {
                "name": "svc",
                "type": "service",
                "service_tracking": "task_in_project",
                "project_id": self.project_global.id,
            }
        )
        product._onchange_service_tracking()
        self.assertFalse(product.project_id)

    def test_write_non_service_type_resets_tracking(self):
        product = self.product_delivery_manual2
        product.write({"type": "consu"})
        self.assertEqual(product.service_tracking, "no")
        self.assertFalse(product.project_id)

    def test_inverse_service_policy_maps_invoice_policy(self):
        product = self.product_delivery_manual1
        product.service_policy = "ordered_prepaid"
        expected_invoice_policy, expected_service_type = (
            product.product_tmpl_id._get_service_to_general("ordered_prepaid")
        )
        self.assertEqual(expected_invoice_policy, "ordered")
        self.assertEqual(product.invoice_policy, "ordered")
        self.assertEqual(product.service_type, expected_service_type)

    def test_tracking_no_rejects_project_links(self):
        with self.assertRaises(ValidationError):
            self.product_delivery_manual1.product_tmpl_id.write(
                {
                    "project_id": self.project_global.id,
                }
            )

    def test_tracking_global_task_rejects_template(self):
        with self.assertRaises(ValidationError):
            self.product_delivery_manual2.product_tmpl_id.write(
                {
                    "project_template_id": self.project_template.id,
                }
            )

    def test_tracking_new_project_rejects_fixed_project(self):
        with self.assertRaises(ValidationError):
            self.product_delivery_manual3.product_tmpl_id.write(
                {
                    "project_id": self.project_global.id,
                }
            )

    def test_template_line_skips_task_link_when_generating(self):
        template = self.env["sale.order.template"].create(
            {
                "name": "Service quote template",
                "sale_order_template_line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_delivery_manual3.id,
                            "product_uom_qty": 1,
                        }
                    )
                ],
            }
        )
        line = template.sale_order_template_line_ids

        res = line.with_context(default_task_id=1)._prepare_order_line_values()
        self.assertIn("task_id", res)
        self.assertFalse(res["task_id"])

        res_no_ctx = line._prepare_order_line_values()
        self.assertNotIn("task_id", res_no_ctx)
