# NOTE: this file was emptied by the workflow-step refactor (d2b1e02a34a5);
# upstream 19.0 carries ~1900 lines of tests here. Repopulation with
# fork-adapted tests is tracked as a dedicated task; the tests below start
# that effort with the SO<->project service behaviors.

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.sale_project.tests.common import TestSaleProjectCommon


@tagged('post_install', '-at_install')
class TestSaleProjectServices(TestSaleProjectCommon):
    """SO service-line lookup and billable-gated workflow step rating."""

    def test_get_first_service_line_returns_service(self):
        """The first service line is returned, skipping consumables."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner_a.id,
            'line_ids': [
                Command.create({
                    'product_id': self.product_consumable.id,
                    'product_uom_qty': 1,
                }),
                Command.create({
                    'product_id': self.product_service_ordered_prepaid.id,
                    'product_uom_qty': 1,
                }),
            ],
        })
        line = order.get_first_service_line()
        self.assertEqual(line.product_id, self.product_service_ordered_prepaid)

    def test_get_first_service_line_requires_service(self):
        """An order without any service product raises UserError."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner_a.id,
            'line_ids': [Command.create({
                'product_id': self.product_consumable.id,
                'product_uom_qty': 1,
            })],
        })
        with self.assertRaises(UserError):
            order.get_first_service_line()

    def test_step_shows_rating_only_for_billable_projects(self):
        """show_rating_active follows the billability of the step projects."""
        step_billable, step_plain = self.env['project.workflow.step'].create([
            {
                'name': 'Billable step',
                'project_ids': [Command.link(self.project_global.id)],
            },
            {
                'name': 'Plain step',
                'project_ids': [Command.link(self.project_template.id)],
            },
        ])
        self.assertTrue(step_billable.show_rating_active)
        self.assertFalse(step_plain.show_rating_active)

    def test_step_onchange_disables_rating_without_billable(self):
        """Ratings switch off when no linked project is billable."""
        step = self.env['project.workflow.step'].new({
            'name': 'Step',
            'rating_active': True,
            'project_ids': [Command.set(self.project_template.ids)],
        })
        step._onchange_project_ids()
        self.assertFalse(step.rating_active)

        step_billable = self.env['project.workflow.step'].new({
            'name': 'Step billable',
            'rating_active': True,
            'project_ids': [Command.set(self.project_global.ids)],
        })
        step_billable._onchange_project_ids()
        self.assertTrue(step_billable.rating_active)
