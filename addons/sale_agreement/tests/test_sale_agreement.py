from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from odoo.addons.sale.tests.common import SaleCommon


@tagged("post_install", "-at_install")
class TestSaleAgreement(SaleCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product.list_price = 50.0
        cls.agreement = cls.env["sale.agreement"].create(
            {
                "partner_id": cls.partner.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": cls.product.id,
                            "product_qty": 100.0,
                            "price_unit": 42.0,
                        }
                    )
                ],
            }
        )

    def test_a_blanket_order_is_named_from_its_sequence(self):
        self.assertTrue(self.agreement.name.startswith("SBO"))

    def test_confirming_needs_a_price_and_a_quantity_on_every_line(self):
        self.agreement.line_ids.price_unit = 0.0
        with self.assertRaisesRegex(UserError, "missing a price"):
            self.agreement.action_confirm()
        self.agreement.line_ids.price_unit = 42.0
        self.agreement.line_ids.product_qty = 0.0
        with self.assertRaisesRegex(UserError, "missing a quantity"):
            self.agreement.action_confirm()

    def _order_against_agreement(self, qty):
        self.agreement.action_confirm()
        with Form(self.env["sale.order"]) as order_form:
            order_form.partner_id = self.partner
            order_form.agreement_id = self.agreement
            with order_form.line_ids.edit(0) as line:
                line.product_qty = qty
        return order_form.record

    def test_an_order_against_the_agreement_takes_its_products_and_prices(self):
        order = self._order_against_agreement(10.0)
        self.assertEqual(order.line_ids.product_id, self.product)
        self.assertEqual(order.line_ids.price_unit, 42.0)
        self.assertIn(self.agreement.name, order.origin)

    def test_confirmed_orders_count_against_the_agreed_quantity(self):
        order = self._order_against_agreement(10.0)
        self.assertEqual(self.agreement.line_ids.qty_ordered, 0.0)
        order.action_confirm()
        self.assertEqual(self.agreement.line_ids.qty_ordered, 10.0)
        self.assertEqual(self.agreement.order_count, 1)

    def test_an_agreement_is_not_closed_while_a_quotation_is_open(self):
        self._order_against_agreement(10.0)
        with self.assertRaisesRegex(UserError, "cancel its related quotations"):
            self.agreement.action_done()

    def test_the_agreed_price_follows_the_unit_of_measure(self):
        dozen = self.env.ref("uom.product_uom_dozen")
        order = self._order_against_agreement(1.0)
        order.line_ids.product_uom_id = dozen
        self.assertAlmostEqual(order.line_ids.price_unit, 42.0 * 12)
