from lxml import etree

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestPurchaseOrderSearchConfirmationDate(AccountTestInvoicingCommon):
    """`date_order` is the RFQ deadline here, not the confirmation date -- they are
    separate fields (`purchase/models/purchase_order.py:175-179`). So the purchase
    order list must offer its own filter and group-by on `date_confirmed`.
    """

    def _search_arch(self):
        view = self.env.ref("purchase.view_purchase_order_search_2")
        return etree.fromstring(
            self.env["purchase.order"].get_view(view_id=view.id, view_type="search")[
                "arch"
            ]
        )

    def test_confirmation_date_filter_is_offered(self):
        node = self._search_arch().find(".//filter[@name='filter_date_confirmed']")
        self.assertIsNotNone(node, "no Confirmation Date filter on the order search")
        self.assertEqual(node.get("date"), "date_confirmed")

    def test_confirmation_date_group_by_is_offered(self):
        node = self._search_arch().find(".//filter[@name='group_date_confirmed']")
        self.assertIsNotNone(node, "no Confirmation Date group-by on the order search")
        self.assertIn("date_confirmed", node.get("context"))

    def test_the_rfq_search_is_left_alone(self):
        view = self.env.ref("purchase.view_purchase_order_search_quotation")
        arch = etree.fromstring(
            self.env["purchase.order"].get_view(view_id=view.id, view_type="search")[
                "arch"
            ]
        )
        self.assertIsNone(
            arch.find(".//filter[@name='filter_date_confirmed']"),
            "an RFQ has no confirmation date; the filter would group everything under None",
        )
