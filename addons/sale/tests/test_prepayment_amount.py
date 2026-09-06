from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.sale.tests.common import SaleCommon


@tagged("post_install", "-at_install")
class TestPrepaymentAmount(SaleCommon):
    """Asking for a down payment as an amount rather than as a percentage.

    The two are one setting seen from two sides: writing either rewrites the
    other, and what the portal charges stays the same figure.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.order = cls.sale_order
        cls.order.require_payment = True
        cls.total = cls.order.amount_total
        assert cls.total > 0, "the fixture order must have an amount to prepay"

    def test_the_amount_follows_the_percentage(self):
        self.order.prepayment_percent = 0.25
        self.assertEqual(
            self.order.prepayment_amount,
            self.order.currency_id.round(self.total * 0.25),
            "a quarter of the order is a quarter of its total",
        )

    def test_typing_an_amount_rewrites_the_percentage(self):
        self.order.prepayment_amount = self.total / 2
        self.assertAlmostEqual(
            self.order.prepayment_percent,
            0.5,
            msg="half the total is fifty percent",
        )

    def test_the_amount_is_what_the_customer_is_asked_to_pay(self):
        wanted = self.order.currency_id.round(self.total / 4)
        self.order.prepayment_amount = wanted
        self.assertEqual(
            self.order._get_prepayment_required_amount(),
            wanted,
            "the portal must charge the amount the salesperson typed",
        )

    def test_more_than_the_total_is_refused(self):
        with self.assertRaises(ValidationError):
            self.order.prepayment_amount = self.total * 2
            self.order.flush_recordset()

    def test_no_online_payment_means_nothing_to_prepay(self):
        self.order.prepayment_percent = 0.25
        self.order.require_payment = False
        self.assertEqual(
            self.order.prepayment_amount,
            0,
            "the amount tracks what the portal would actually ask for",
        )

    def test_an_order_worth_nothing_does_not_divide_by_zero(self):
        # require_payment stays off: _check_prepayment_percent already refuses a
        # zero percentage on an order that asks for a payment, so an order with
        # no total cannot ask for one either. What is under test here is only
        # that writing the amount does not divide by amount_total.
        empty = self.empty_order
        self.assertEqual(empty.amount_total, 0)
        empty.prepayment_amount = 0
        empty.flush_recordset()
        self.assertEqual(empty.prepayment_percent, 0)
