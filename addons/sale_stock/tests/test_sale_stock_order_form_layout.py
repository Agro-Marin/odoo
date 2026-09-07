from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSaleStockOrderFormLayout(TransactionCase):
    """The Delivery fields must not follow the date into the order header."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.arch = etree.fromstring(
            cls.env["sale.order"].get_view(
                cls.env.ref("sale.view_sale_order_form").id, "form"
            )["arch"]
        )

    def _shipping_group(self):
        groups = self.arch.xpath(
            "//page[@name='other_information']//group[@name='sale_shipping']"
        )
        self.assertEqual(len(groups), 1)
        return groups[0]

    def test_the_delivery_fields_stayed_in_the_other_info_tab(self):
        """They used to be anchored `before` the label that now lives in the
        header; anchored on the group instead, they stay where they were."""
        for name in (
            "warehouse_id",
            "incoterm_id",
            "incoterm_location",
            "picking_policy",
            "date_effective",
        ):
            with self.subTest(field=name):
                self.assertTrue(
                    self._shipping_group().xpath(f".//field[@name='{name}']"),
                    f"{name} left the Delivery group",
                )
                self.assertFalse(
                    self.arch.xpath(
                        f"//group[@name='order_details']//field[@name='{name}']"
                    ),
                    f"{name} was dragged into the order header",
                )

    def test_the_delivery_group_is_visible_again(self):
        """`sale` hides it while it is empty; whoever fills it must unhide it."""
        self.assertIsNone(self._shipping_group().get("invisible"))

    def test_the_delivery_status_badge_sits_next_to_the_date(self):
        """That pairing is the point of the move: date and status read together."""
        badge = self.arch.xpath(
            "//group[@name='order_details']"
            "//div[@name='date_commitment_div']/field[@name='transfer_state']"
        )
        self.assertEqual(len(badge), 1)
        self.assertEqual(badge[0].get("widget"), "badge")

    def test_the_rescheduling_popover_follows_the_date_it_annotates(self):
        """It was anchored on `date_planned` inside the tab, which no longer
        holds it -- an anchor that would have failed the view's own validation."""
        self.assertTrue(
            self.arch.xpath(
                "//group[@name='order_details']"
                "//div[@name='date_commitment_div']/field[@name='json_popover']"
            )
        )
