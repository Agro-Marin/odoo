from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.sale_project.tests.common import TestSaleProjectCommon


@tagged("post_install", "-at_install")
class TestServiceProductConfig(TestSaleProjectCommon):
    """Service tracking configuration guards on products and template lines."""

    def test_onchange_tracking_no_clears_project_and_template(self):
        """Switching tracking to 'no' clears both project and template."""
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
        """A global-project task product keeps the project, drops the template."""
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
        """A new-project product cannot point to a fixed global project."""
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
        """Turning a service into a consumable resets tracking and project."""
        product = self.product_delivery_manual2
        product.write({"type": "consu"})
        self.assertEqual(product.service_tracking, "no")
        self.assertFalse(product.project_id)

    def test_inverse_service_policy_maps_invoice_policy(self):
        """Setting the service policy drives invoice policy and service type.

        The service type is read from the module's own mapping rather than spelled
        out: `_get_service_to_general_map` is an extension point, and a bridge module
        legitimately re-points a policy at its own tracking -- `sale_timesheet` maps
        `ordered_prepaid` to `timesheet` where this module alone maps it to `manual`.
        Pinning the literal here asserted that no such module is installed, which is
        not what this test is about. The invoice policy is spelled out because every
        map agrees on it.
        """
        product = self.product_delivery_manual1
        product.service_policy = "ordered_prepaid"
        expected_invoice_policy, expected_service_type = (
            product.product_tmpl_id._get_service_to_general("ordered_prepaid")
        )
        self.assertEqual(expected_invoice_policy, "ordered")
        self.assertEqual(product.invoice_policy, "ordered")
        self.assertEqual(product.service_type, expected_service_type)

    def test_tracking_no_rejects_project_links(self):
        """A non-generating product must not carry project nor template."""
        with self.assertRaises(ValidationError):
            self.product_delivery_manual1.product_tmpl_id.write(
                {
                    "project_id": self.project_global.id,
                }
            )

    def test_tracking_global_task_rejects_template(self):
        """A global-task product must not carry a project template."""
        with self.assertRaises(ValidationError):
            self.product_delivery_manual2.product_tmpl_id.write(
                {
                    "project_template_id": self.project_template.id,
                }
            )

    def test_tracking_new_project_rejects_fixed_project(self):
        """A project-generating product must not carry a fixed project."""
        with self.assertRaises(ValidationError):
            self.product_delivery_manual3.product_tmpl_id.write(
                {
                    "project_id": self.project_global.id,
                }
            )

    def test_template_line_skips_task_link_when_generating(self):
        """Template lines drop task_id for task-generating service products."""
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
