from lxml import etree

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.libs.text import str2bool
from odoo.tests import tagged
from odoo.tools.misc import file_path
from odoo.tools.safe_eval import safe_eval

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

    def test_demo_project_template_satisfies_its_own_fields_domain(self):
        """Whatever the demo declares for ``so_template_project`` must be
        pickable in the dropdown that references it.

        ``product_template.project_template_id`` only offers real templates
        (`models/product_template.py`), so an archived plain project is
        referenced by three demo products while being unpickable in the very
        dropdown that references it -- and it takes the plain ``copy()`` branch
        of ``_timesheet_create_project`` instead of
        ``action_create_from_template``.

        A fresh ``--with-demo`` database cannot be built on this branch (base's
        own ``res_users_data.xml`` fails to load), so the record's declared
        values are read straight from the demo file and replayed here, with
        ``str2bool`` interpreting the booleans the way ``tools/convert.py:475``
        does. Only the fields the domain actually reads are replayed; the stage
        links are irrelevant to it.
        """
        root = etree.parse(
            file_path("sale_project/data/sale_project_demo.xml")
        ).getroot()
        node = root.find('.//record[@id="so_template_project"]')
        self.assertIsNotNone(node, "The demo template record must still exist.")

        declared = {"name": "Replay of so_template_project"}
        for field in node.findall("field"):
            name = field.get("name")
            if name not in ("active", "is_template", "allow_billable"):
                continue
            raw = field.get("eval") or (field.text or "")
            declared[name] = str2bool(raw.strip(), default=True)

        replica = (
            self.env["project.project"].with_context(active_test=False).create(declared)
        )

        # The domain the web client actually receives for the field, evaluated
        # with the values one of the referencing demo products declares -- also
        # read from the file, since that product is demo data too.
        product = root.find('.//record[@id="product_service_create_project_and_task"]')
        self.assertEqual(
            product.find('field[@name="project_template_id"]').get("ref"),
            "so_template_project",
            "The demo product should still point at the demo template.",
        )
        description = self.env["product.template"].fields_get(["project_template_id"])[
            "project_template_id"
        ]
        domain = safe_eval(
            description["domain"],
            {
                # the product declares no company, so the field falls back to
                # the company-less branch of the domain
                "company_id": False,
                "current_company_id": self.env.company.id,
                "service_policy": product.find('field[@name="service_policy"]').text,
            },
        )
        self.assertIn(
            replica,
            self.env["project.project"].search(domain),
            "The demo template must be pickable in the dropdown that uses it.",
        )
