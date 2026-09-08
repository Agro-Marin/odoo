from lxml.etree import fromstring

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStockReportColumnOrder(TransactionCase):
    """The Stock report is named for its quantities, so they lead the row.

    `stock_account` hangs the cost and value columns off this list; inserting
    them ahead of `qty_available` pushed the two figures the report exists to
    show behind two money columns.
    """

    def test_quantity_columns_precede_valuation_columns(self):
        arch = self.env["product.product"].get_view(
            view_id=self.env.ref("stock.product_product_stock_tree").id,
            view_type="list",
        )["arch"]
        names = [node.get("name") for node in fromstring(arch).iterfind("./field")]

        for quantity in ("qty_available", "qty_free"):
            self.assertIn(
                quantity,
                names,
                "the Stock report must still carry its quantity columns",
            )
        for money in ("avg_cost", "total_value"):
            self.assertIn(
                money,
                names,
                "stock_account must still contribute its valuation columns",
            )
            for quantity in ("qty_available", "qty_free"):
                self.assertLess(
                    names.index(quantity),
                    names.index(money),
                    f"{quantity!r} must be listed before {money!r}",
                )
