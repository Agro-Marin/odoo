from odoo.tests import tagged

from .common import TestCommonSaleTimesheet


@tagged("-at_install", "post_install")
class TestUpsellWarning(TestCommonSaleTimesheet):
    def test_display_upsell_warning(self):
        self.product_order_timesheet1.write(
            {
                "service_upsell_threshold": 0.5,
            }
        )

        so = self.env["sale.order"].create(
            {
                "partner_id": self.partner_a.id,
                "partner_invoice_id": self.partner_a.id,
                "partner_shipping_id": self.partner_a.id,
            }
        )

        self.env["sale.order.line"].create(
            {
                "order_id": so.id,
                "product_id": self.product_order_timesheet1.id,
                "product_qty": 10,
            }
        )
        so.action_confirm()

        project = self.env["project.project"].create(
            {
                "name": "Project",
                "allow_timesheets": True,
                "allow_billable": True,
                "partner_id": self.partner_a.id,
                "account_id": self.analytic_account_sale.id,
            }
        )
        task = self.env["project.task"].create(
            {
                "name": "Task Test",
                "project_id": project.id,
            }
        )
        task._compute_sale_line_id()

        timesheet = self.env["account.analytic.line"].create(
            {
                "name": "Test Line",
                "unit_amount": 5,
                "employee_id": self.employee_manager.id,
                "project_id": project.id,
                "task_id": task.id,
            }
        )
        timesheet._compute_so_line()
        so.line_ids._compute_qty_transferred()
        so.line_ids._compute_invoice_state()
        so._compute_invoice_state()
        so._compute_field_value(so._fields["invoice_state"])

        self.assertEqual(
            len(so.activity_search(["mail.mail_activity_data_todo"])),
            0,
            "No upsell warning should appear in the SO.",
        )
        timesheet.write(
            {
                "unit_amount": 6,
            }
        )
        timesheet._compute_so_line()
        so.line_ids._compute_qty_transferred()
        so.line_ids._compute_invoice_state()
        so._compute_invoice_state()
        so._compute_field_value(so._fields["invoice_state"])

        self.assertEqual(
            len(so.activity_search(["mail.mail_activity_data_todo"])),
            1,
            "A upsell warning should appear in the SO.",
        )

    def test_display_upsell_warning_when_invoiced(self):

        self.product_order_timesheet1.write(
            {
                "service_upsell_threshold": 100,
            }
        )

        so = self.env["sale.order"].create(
            {
                "partner_id": self.partner_a.id,
                "partner_invoice_id": self.partner_a.id,
                "partner_shipping_id": self.partner_a.id,
            }
        )

        self.env["sale.order.line"].create(
            {
                "order_id": so.id,
                "name": self.product_order_timesheet1.name,
                "product_id": self.product_order_timesheet1.id,
                "product_qty": 1,
                "price_unit": self.product_order_timesheet1.list_price,
            }
        )
        so.action_confirm()

        project = self.env["project.project"].create(
            {
                "name": "Project",
                "allow_timesheets": True,
                "allow_billable": True,
                "partner_id": self.partner_a.id,
                "account_id": self.analytic_account_sale.id,
            }
        )
        task = self.env["project.task"].create(
            {
                "name": "Task Test",
                "project_id": project.id,
                "sale_line_id": so.line_ids.id,
            }
        )

        self.env["account.analytic.line"].create(
            {
                "name": "Test Line",
                "unit_amount": 50,
                "employee_id": self.employee_manager.id,
                "project_id": project.id,
                "task_id": task.id,
            }
        )
        so.line_ids._compute_qty_transferred()

        so._create_invoices()
        so._compute_field_value(so._fields["invoice_state"])

        self.assertEqual(
            len(so.activity_search(["mail.mail_activity_data_todo"])),
            0,
            "No upsell warning should appear in the SO.",
        )

    def test_display_upsell_warning_multiple_times(self):

        self.product_order_timesheet1.write(
            {
                "service_upsell_threshold": 1.0,
            }
        )

        so = self.env["sale.order"].create(
            {
                "partner_id": self.partner_a.id,
                "partner_invoice_id": self.partner_a.id,
                "partner_shipping_id": self.partner_a.id,
            }
        )

        self.env["sale.order.line"].create(
            {
                "order_id": so.id,
                "product_id": self.product_order_timesheet1.id,
                "product_qty": 10,
            }
        )
        so.action_confirm()

        project = self.env["project.project"].create(
            {
                "name": "Project",
                "allow_timesheets": True,
                "allow_billable": True,
                "partner_id": self.partner_a.id,
                "account_id": self.analytic_account_sale.id,
            }
        )
        task = self.env["project.task"].create(
            {
                "name": "Task Test",
                "project_id": project.id,
            }
        )
        task._compute_sale_line_id()

        self.env["account.analytic.line"].create(
            {
                "name": "Timesheet1",
                "unit_amount": 15,
                "employee_id": self.employee_manager.id,
                "project_id": project.id,
                "task_id": task.id,
            }
        )
        so.line_ids._compute_qty_transferred()
        so._compute_field_value(so._fields["invoice_state"])
        self.assertEqual(
            len(so.activity_search(["mail.mail_activity_data_todo"])),
            1,
            "An upsell warning should appear in the SO.",
        )

        so.line_ids.write(
            {
                "product_qty": so.line_ids.qty_transferred,
            }
        )

        so.activity_search(["mail.mail_activity_data_todo"])._action_done()

        so._create_invoices()
        so._compute_field_value(so._fields["invoice_state"])
        self.assertEqual(
            len(so.activity_search(["mail.mail_activity_data_todo"])),
            0,
            "No upsell warning should appear in the SO.",
        )

        self.env["account.analytic.line"].create(
            {
                "name": "Timesheet2",
                "unit_amount": 5,
                "employee_id": self.employee_manager.id,
                "project_id": project.id,
                "task_id": task.id,
            }
        )
        so.line_ids._compute_qty_transferred()
        so._compute_field_value(so._fields["invoice_state"])

        self.assertEqual(
            len(so.activity_search(["mail.mail_activity_data_todo"])),
            1,
            "A upsell warning should appear in the SO.",
        )
