from odoo import Command
from odoo.tests import tagged

from odoo.addons.sale_project.tests.common import TestSaleProjectCommon


@tagged('post_install', '-at_install')
class TestProjectTemplateCreateWizard(TestSaleProjectCommon):
    """Project creation from a sale order through the template wizard."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sale_order = cls.env['sale.order'].create({
            'partner_id': cls.partner_a.id,
            'line_ids': [Command.create({
                'product_id': cls.product_delivery_manual3.id,
                'product_uom_qty': 1,
            })],
        })
        cls.Wizard = cls.env['project.template.create.wizard']

    def test_role_lines_follow_template(self):
        """One role line per template task role; cleared without template."""
        role = self.env['project.role'].create({'name': 'Reviewer'})
        self.env['project.task'].create({
            'name': 'Template task',
            'project_id': self.project_template.id,
            'role_ids': [Command.set(role.ids)],
        })
        # The wizard is UI-driven: instantiate through the onchange path
        # (new), as the template action does via context defaults.
        wizard = self.Wizard.new({
            'name': 'From template',
            'template_id': self.project_template.id,
        })
        self.assertEqual(wizard.role_to_users_ids.role_id, role)

        wizard.template_id = False
        self.assertFalse(wizard.role_to_users_ids.role_id)

    def test_whitelist_partner_only_for_billable_template(self):
        """partner_id joins the whitelist only when the template is billable."""
        wizard = self.Wizard.create({
            'name': 'Non billable',
            'template_id': self.project_template.id,
        })
        self.assertNotIn('partner_id', wizard._get_template_whitelist_fields())

        self.project_template.allow_billable = True
        wizard_billable = self.Wizard.create({
            'name': 'Billable',
            'template_id': self.project_template.id,
        })
        self.assertIn('partner_id', wizard_billable._get_template_whitelist_fields())

    def test_open_template_view_propagates_sale_defaults(self):
        """Sale defaults reach the action context when opened from a SO."""
        so_line = self.sale_order.line_ids[:1]
        action = self.Wizard.with_context(
            from_sale_order_action=True,
            default_partner_id=self.sale_order.partner_id.id,
            default_reinvoiced_sale_order_id=self.sale_order.id,
            default_sale_line_id=so_line.id,
        ).action_open_template_view()
        self.assertEqual(
            action['context']['default_partner_id'], self.sale_order.partner_id.id,
        )
        self.assertEqual(
            action['context']['default_reinvoiced_sale_order_id'], self.sale_order.id,
        )
        self.assertEqual(action['context']['default_sale_line_id'], so_line.id)

    def test_create_project_from_so_single_coded_line_name(self):
        """Without template, a single coded line names the project SO - [CODE] product."""
        wizard = self.Wizard.with_context(
            default_sale_order_id=self.sale_order.id,
        ).create({'name': 'ignored'})
        wizard.action_create_project_from_so()

        product = self.product_delivery_manual3
        expected = (
            f"{self.sale_order.name} - [{product.default_code}] {product.name}"
        )
        project = self.env['project.project'].search([('name', '=', expected)])
        self.assertEqual(len(project), 1)
        self.assertEqual(project.partner_id, self.sale_order.partner_id)
        self.assertEqual(project.company_id, self.sale_order.company_id)

    def test_create_project_from_so_uncoded_line_name(self):
        """Without default_code the project is named SO - product name."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner_a.id,
            'line_ids': [Command.create({
                'product_id': self.product_service_ordered_prepaid.id,
                'product_uom_qty': 1,
            })],
        })
        wizard = self.Wizard.with_context(
            default_sale_order_id=order.id,
        ).create({'name': 'ignored'})
        wizard.action_create_project_from_so()

        expected = f"{order.name} - {self.product_service_ordered_prepaid.name}"
        self.assertTrue(self.env['project.project'].search([('name', '=', expected)]))

    def test_create_project_from_so_multiline_name(self):
        """With several lines the project simply takes the SO name."""
        self.sale_order.line_ids = [Command.create({
            'product_id': self.product_service_ordered_prepaid.id,
            'product_uom_qty': 1,
        })]
        wizard = self.Wizard.with_context(
            default_sale_order_id=self.sale_order.id,
        ).create({'name': 'ignored'})
        wizard.action_create_project_from_so()

        self.assertTrue(self.env['project.project'].search(
            [('name', '=', self.sale_order.name)],
        ))

    def test_create_project_from_so_with_template(self):
        """With a template the project is created from it, named by the wizard."""
        wizard = self.Wizard.with_context(
            default_sale_order_id=self.sale_order.id,
        ).create({
            'name': 'Templated project from SO',
            'template_id': self.project_template.id,
        })
        action = wizard.action_create_project_from_so()

        project = self.env['project.project'].search(
            [('name', '=', 'Templated project from SO')],
        )
        self.assertEqual(len(project), 1)
        self.assertEqual(action['res_model'], 'project.task')
