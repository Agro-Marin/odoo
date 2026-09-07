from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSaleOrderFormLayout(TransactionCase):
    """Where the promised delivery date sits on the order form."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.arch = etree.fromstring(
            cls.env["sale.order"].get_view(
                cls.env.ref("sale.view_sale_order_form").id, "form"
            )["arch"]
        )

    def test_the_promised_delivery_date_is_in_the_order_header(self):
        """It is read on every order, so it belongs beside the payment terms."""
        self.assertTrue(
            self.arch.xpath(
                "//group[@name='order_details']"
                "//div[@name='date_commitment_div']/field[@name='date_commitment']"
            )
        )

    def test_the_promised_delivery_date_left_the_other_info_tab(self):
        """Reading it used to cost opening a tab."""
        self.assertFalse(
            self.arch.xpath(
                "//page[@name='other_information']//field[@name='date_commitment']"
            )
        )

    def test_the_shipping_group_survives_the_move(self):
        """`sale_stock` and `delivery` both inherit into it, and `delivery` does
        not depend on `sale_stock`, so neither of them can declare it."""
        self.assertTrue(
            self.arch.xpath(
                "//page[@name='other_information']//group[@name='sale_shipping']"
            )
        )
