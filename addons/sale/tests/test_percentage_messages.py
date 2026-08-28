from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPercentageMessages(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env["res.partner"].create({"name": "Percent client"})
        cls.product = cls.env["product.product"].create(
            {"name": "Percent product", "type": "service", "list_price": 100.0}
        )

    def _order(self):
        return self.env["sale.order"].create(
            {
                "partner_id": self.customer.id,
                "line_ids": [
                    (0, 0, {"product_id": self.product.id, "product_qty": 1}),
                ],
            }
        )

    def test_prepayment_percentage_message_is_not_double_escaped(self):
        order = self._order()
        with self.assertRaises(ValidationError) as caught:
            order.write({"require_payment": True, "prepayment_percent": 0.0})
        self.assertNotIn("%%", caught.exception.args[0])
        self.assertIn("100%.", caught.exception.args[0])

    def test_discount_percentage_message_is_not_double_escaped(self):
        order = self._order()
        wizard = self.env["sale.order.discount"].create(
            {"sale_order_id": order.id, "discount_type": "so_discount"}
        )
        with self.assertRaises(ValidationError) as caught:
            wizard.discount_percentage = 1.5
        self.assertNotIn("%%", caught.exception.args[0])

    def test_down_payment_percentage_message_is_not_double_escaped(self):
        order = self._order()
        order.action_confirm()
        wizard = self.env["sale.advance.payment.inv"].create(
            {
                "sale_order_ids": [(6, 0, order.ids)],
                "advance_payment_method": "percentage",
                "amount": 150.0,
            }
        )
        with self.assertRaises(UserError) as caught:
            wizard.create_invoices()
        self.assertNotIn("%%", caught.exception.args[0])
