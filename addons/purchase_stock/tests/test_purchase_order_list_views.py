from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestPurchaseOrderKpiListReceiptStatus(TransactionCase):
    """Receipt status must be offerable on the list the Purchases menu opens.

    `transfer_state` reached only `view_purchase_order_list_2`, which
    `action_purchase_order_2` filters to `state = done`. The list behind
    `action_purchase_order` -- the one at `path="purchases"`, whose domain is
    empty -- was never inherited by `purchase_stock`, so the column could not
    even be switched on there.
    """

    def _kpi_list_arch(self):
        view = self.env.ref("purchase.view_purchase_order_list_kpis")
        arch = self.env["purchase.order"].get_view(view.id, "list")["arch"]
        return etree.fromstring(arch)

    def test_receipt_status_is_an_optional_column_of_the_kpi_list(self):
        nodes = self._kpi_list_arch().xpath("//field[@name='transfer_state']")

        self.assertTrue(
            nodes,
            "transfer_state must be a column of view_purchase_order_list_kpis",
        )
        self.assertEqual(nodes[0].get("widget"), "badge")
        self.assertEqual(
            nodes[0].get("optional"),
            "hide",
            "off by default, like the same column on view_purchase_order_list_2",
        )

    def test_the_late_decoration_has_the_helper_field_it_reads(self):
        arch = self._kpi_list_arch()
        node = arch.xpath("//field[@name='transfer_state']")[0]

        self.assertIn(
            "date_effective",
            node.get("decoration-danger", ""),
            "the late badge is decided against the first receipt's completion date",
        )
        self.assertTrue(
            arch.xpath("//field[@name='date_effective']"),
            "date_effective must be in the arch for the decoration to evaluate",
        )
