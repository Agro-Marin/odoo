from odoo.tests import tagged

from odoo.addons.purchase.tests.test_purchase_invoice import TestPurchaseToInvoiceCommon


@tagged("-at_install", "post_install")
class TestPurchaseDiscountWizard(TestPurchaseToInvoiceCommon):
    def _order(self):
        po = self.init_purchase(
            confirm=False, products=[self.product_order], taxes=self.env["account.tax"]
        )
        po.line_ids.product_qty = 10.0
        po.line_ids.price_unit = 100.0
        return po

    def _apply(self, po, **vals):
        wizard = (
            self.env["purchase.order.discount"]
            .with_context(active_id=po.id)
            .create(vals)
        )
        wizard.action_apply_discount()
        return wizard

    def test_a_percentage_on_every_line_sets_their_discount(self):
        po = self._order()
        self._apply(po, discount_type="sol_discount", discount_percentage=0.1)
        self.assertEqual(po.line_ids.discount, 10.0)
        self.assertAlmostEqual(po.amount_untaxed, 900.0)

    def test_a_global_percentage_adds_a_discount_line(self):
        po = self._order()
        self._apply(po, discount_type="so_discount", discount_percentage=0.1)
        discount_product = po.company_id.purchase_config_id.purchase_discount_product_id
        self.assertTrue(discount_product.purchase_ok)
        discount_line = po.line_ids.filtered(
            lambda line: line.product_id == discount_product
        )
        self.assertEqual(len(discount_line), 1)
        self.assertTrue(discount_line._is_global_discount())
        self.assertAlmostEqual(discount_line.price_subtotal, -100.0)
        self.assertAlmostEqual(po.amount_untaxed, 900.0)

    def test_a_fixed_amount_lowers_the_total_by_that_amount(self):
        po = self._order()
        total_before = po.amount_total
        self._apply(po, discount_type="amount", discount_amount=150.0)
        self.assertAlmostEqual(po.amount_total, total_before - 150.0)
