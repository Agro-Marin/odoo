# NOTE: this file was emptied by the workflow-step refactor (d2b1e02a34a5);
# upstream 19.0 carries ~1900 lines of tests here. Repopulation with
# fork-adapted tests is tracked as a dedicated task; the tests below start
# that effort with the SO<->project service behaviors.

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.sale_project.tests.common import TestSaleProjectCommon


@tagged("post_install", "-at_install")
class TestSaleProjectServices(TestSaleProjectCommon):
    """SO service-line lookup and billable-gated workflow step rating."""

    def test_get_first_service_line_returns_service(self):
        """The first service line is returned, skipping consumables."""
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_consumable.id,
                            "product_uom_qty": 1,
                        }
                    ),
                    Command.create(
                        {
                            "product_id": self.product_service_ordered_prepaid.id,
                            "product_uom_qty": 1,
                        }
                    ),
                ],
            }
        )
        line = order.get_first_service_line()
        self.assertEqual(line.product_id, self.product_service_ordered_prepaid)

    def test_get_first_service_line_requires_service(self):
        """An order without any service product raises UserError."""
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_consumable.id,
                            "product_uom_qty": 1,
                        }
                    )
                ],
            }
        )
        with self.assertRaises(UserError):
            order.get_first_service_line()

    def test_step_shows_rating_only_for_billable_projects(self):
        """show_rating_active follows the billability of the step projects."""
        step_billable, step_plain = self.env["project.workflow.step"].create(
            [
                {
                    "name": "Billable step",
                    "project_ids": [Command.link(self.project_global.id)],
                },
                {
                    "name": "Plain step",
                    "project_ids": [Command.link(self.project_template.id)],
                },
            ]
        )
        self.assertTrue(step_billable.show_rating_active)
        self.assertFalse(step_plain.show_rating_active)

    def test_step_onchange_disables_rating_without_billable(self):
        """Ratings switch off when no linked project is billable."""
        step = self.env["project.workflow.step"].new(
            {
                "name": "Step",
                "rating_active": True,
                "project_ids": [Command.set(self.project_template.ids)],
            }
        )
        step._onchange_project_ids()
        self.assertFalse(step.rating_active)

        step_billable = self.env["project.workflow.step"].new(
            {
                "name": "Step billable",
                "rating_active": True,
                "project_ids": [Command.set(self.project_global.ids)],
            }
        )
        step_billable._onchange_project_ids()
        self.assertTrue(step_billable.rating_active)

    def test_has_any_so_to_invoice_uses_fork_state_spelling(self):
        """The flag must match this fork's ``to do`` invoice state.

        Regression: the lookup passed upstream's ``to invoice`` spelling,
        which is not in this fork's selection (no / to do / partial / done /
        over done), so ``has_any_so_to_invoice`` was always False and
        ``action_create_invoice`` always defaulted the wizard to a percentage
        down payment.
        """
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            # A SERVICE: sale_timesheet constrains a billable
                            # project's sale_line_id to one, and this test errored
                            # on that constraint whenever sale_timesheet happened
                            # to be installed alongside. Ordered-policy, so the
                            # line is invoiceable the moment the order is
                            # confirmed -- which is what the assertions below are
                            # actually about.
                            "product_id": self.product_service_ordered_prepaid.id,
                            "product_qty": 5,
                            "tax_ids": False,
                        }
                    ),
                ],
            }
        )
        order.action_confirm()
        self.project_global.sale_line_id = order.line_ids[0]
        self.env.invalidate_all()

        self.assertEqual(order.invoice_state, "to do")
        self.assertTrue(self.project_global.has_any_so_to_invoice)

        invoice = order._create_invoices()
        invoice.action_post()
        self.env.invalidate_all()

        self.assertEqual(order.invoice_state, "done")
        self.assertFalse(self.project_global.has_any_so_to_invoice)

    def test_project_update_description_renders_for_a_billable_project(self):
        """The default description template reads the sale-order-line keys that
        ``_get_template_values`` actually puts in the dict.

        Regression: the Python half of this fork's ``product_uom_qty`` ->
        ``product_qty`` split was done and the QWeb half was not, so the
        template asked for ``sol['product_uom_qty']`` against a dict built from
        ``product_qty``. Creating a Project Update on a billable project raised
        ``KeyError: 'product_uom_qty'`` — a 500 behind an "Oops!" dialog, on a
        button in the project dashboard.
        """
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_service_ordered_prepaid.id,
                            "product_qty": 5,
                            "tax_ids": False,
                        }
                    ),
                ],
            }
        )
        order.action_confirm()
        project = order.project_ids[:1] or self.project_global
        project.allow_billable = True
        project.sale_line_id = order.line_ids[0]

        description = self.env["project.update"]._prepare_description(project)
        self.assertTrue(description)

        update = self.env["project.update"].create(
            {"name": "Update", "project_id": project.id, "status": "on_track"}
        )
        self.assertTrue(update.exists())
