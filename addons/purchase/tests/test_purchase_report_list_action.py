from lxml import etree

from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestPurchaseReportListOpensOrder(AccountTestInvoicingCommon):
    """Purchase Analysis is a graph/pivot action; its list is reached by drilling
    into a cell. Clicking a row there must open the order, not an auto-generated
    `purchase.report` form.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.order = cls.env["purchase.order"].create(
            {
                "partner_id": cls.partner_a.id,
                "line_ids": [
                    Command.create({"product_id": cls.product_a.id, "product_qty": 4.0})
                ],
            }
        )
        cls.order.action_confirm()
        cls.env.flush_all()

    def test_analysis_list_rows_open_the_order(self):
        arch = etree.fromstring(
            self.env["purchase.report"].get_view(view_type="list")["arch"]
        )
        self.assertEqual(arch.get("action"), "action_view_order")
        self.assertEqual(arch.get("type"), "object")

    def test_the_named_action_returns_the_source_order(self):
        row = self.env["purchase.report"].search(
            [("order_reference", "=", f"purchase.order,{self.order.id}")], limit=1
        )
        self.assertTrue(row, "the confirmed order must show up in Purchase Analysis")
        action = row.action_view_order()
        self.assertEqual(action["res_model"], "purchase.order")
        self.assertEqual(action["res_id"], self.order.id)
