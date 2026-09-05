from odoo import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("-at_install", "post_install")
class TestPurchaseReportGroupByOrder(AccountTestInvoicingCommon):
    """`purchase.report` must be groupable by purchase order.

    Our report exposes the order as a `fields.Reference` (`order_reference`), and
    `reference` is absent from the web client's `GROUPABLE_TYPES`, so that field
    can serve neither a quick filter nor a custom group.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.order_1, cls.order_2 = cls.env["purchase.order"].create(
            [
                {
                    "partner_id": cls.partner_a.id,
                    "line_ids": [
                        Command.create(
                            {
                                "product_id": cls.product_a.id,
                                "product_qty": 2,
                                "price_unit": 100.0,
                            },
                        ),
                        Command.create(
                            {
                                "product_id": cls.product_b.id,
                                "product_qty": 1,
                                "price_unit": 50.0,
                            },
                        ),
                    ],
                },
                {
                    "partner_id": cls.partner_a.id,
                    "line_ids": [
                        Command.create(
                            {
                                "product_id": cls.product_a.id,
                                "product_qty": 1,
                                "price_unit": 30.0,
                            },
                        ),
                    ],
                },
            ],
        )

    def test_report_groups_by_order(self):
        orders = self.order_1 + self.order_2
        groups = self.env["purchase.report"]._read_group(
            [("order_id", "in", orders.ids)],
            groupby=["order_id"],
            aggregates=["__count"],
        )

        self.assertEqual(
            {order.id: count for order, count in groups},
            {self.order_1.id: 2, self.order_2.id: 1},
            "one group per order, holding that order's lines",
        )

    def test_group_by_order_is_offered_in_the_search_view(self):
        view = self.env.ref("purchase.view_purchase_report_search")
        arch = self.env["purchase.report"].get_view(view.id, "search")["arch"]

        self.assertIn("group_order_id", arch)
