from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAnalyticPurchaseButton(TransactionCase):
    """Purchase smart button on an analytic account."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plan = (
            cls.env['account.analytic.plan'].search([], limit=1)
            or cls.env['account.analytic.plan'].create({'name': 'Test plan'})
        )
        cls.account = cls.env['account.analytic.account'].create({
            'name': 'Analytic target', 'plan_id': cls.plan.id,
        })
        cls.vendor = cls.env['res.partner'].create({'name': 'Analytic vendor'})
        cls.product = cls.env['product.product'].create({
            'name': 'Analytic part', 'type': 'consu',
            'purchase_ok': True, 'standard_price': 10.0,
        })

    def _billed_order(self, account=None):
        order = self.env['purchase.order'].create({
            'partner_id': self.vendor.id,
            'line_ids': [Command.create({
                'product_id': self.product.id,
                'product_qty': 2,
            })],
        })
        order.action_confirm()
        distribution = {str((account or self.account).id): 100}
        invoice = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.vendor.id,
            'invoice_date': '2026-08-01',
            'invoice_line_ids': [Command.create({
                'product_id': self.product.id,
                'quantity': 2,
                'price_unit': 10.0,
                'purchase_line_ids': [Command.set(order.line_ids.ids)],
                'analytic_distribution': distribution,
            })],
        })
        invoice.action_post()
        return order

    def test_count_reaches_the_account_through_the_bill(self):
        """An order billed against the account is counted on it."""
        self._billed_order()
        self.account.invalidate_recordset(['purchase_order_count'])
        self.assertEqual(self.account.purchase_order_count, 1)

    def test_account_without_bills_counts_zero(self):
        """An analytic account nobody billed reports nothing (boundary)."""
        idle = self.env['account.analytic.account'].create({
            'name': 'Idle account', 'plan_id': self.plan.id,
        })
        self.assertEqual(idle.purchase_order_count, 0)

    def test_orders_of_another_account_are_not_counted(self):
        """Spending charged elsewhere never reaches this account."""
        other = self.env['account.analytic.account'].create({
            'name': 'Other account', 'plan_id': self.plan.id,
        })
        self._billed_order(account=other)
        self.account.invalidate_recordset(['purchase_order_count'])
        self.assertEqual(self.account.purchase_order_count, 0)

    def test_button_opens_the_single_order_as_a_form(self):
        """With one order the button lands directly on its form."""
        order = self._billed_order()
        action = self.account.action_view_purchase_orders()
        self.assertEqual(action['view_mode'], 'form')
        self.assertEqual(action['res_id'], order.id)

    def test_button_opens_a_list_for_several_orders(self):
        """With several orders the button opens the filtered list."""
        first = self._billed_order()
        second = self._billed_order()
        action = self.account.action_view_purchase_orders()
        self.assertEqual(action['view_mode'], 'list,form')
        self.assertNotIn('res_id', action)
        listed = action['domain'][0][2]
        self.assertIn(first.id, listed)
        self.assertIn(second.id, listed)
