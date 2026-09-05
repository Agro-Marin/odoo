from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestPurchaseOrderKpiListColumns(TransactionCase):
    """The list the Purchases menu opens must offer the same columns as its siblings.

    `view_purchase_order_list_kpis` is the view of `action_purchase_order`
    (`path="purchases"`, empty domain, so it holds confirmed orders too). Its
    two sibling lists paint `invoice_state` as a coloured badge; this one was
    left as bare text.
    """

    def _kpi_list_arch(self):
        view = self.env.ref("purchase.view_purchase_order_list_kpis")
        arch = self.env["purchase.order"].get_view(view.id, "list")["arch"]
        return etree.fromstring(arch)

    def _field(self, name):
        nodes = self._kpi_list_arch().xpath(f"//field[@name='{name}']")
        self.assertTrue(nodes, f"{name} is not a column of the KPI list")
        return nodes[0]

    def test_billing_status_is_a_badge(self):
        self.assertEqual(self._field("invoice_state").get("widget"), "badge")

    def test_billing_status_badge_covers_every_value_of_the_selection(self):
        node = self._field("invoice_state")
        decorated = {
            attr[len("decoration-") :]: expr
            for attr, expr in node.attrib.items()
            if attr.startswith("decoration-")
        }

        self.assertEqual(
            set(decorated),
            {"warning", "info", "success", "danger"},
            "our selection has five values, not upstream's three: 'no' stays "
            "undecorated and the other four each get a colour",
        )
        for value, decoration in (
            ("to do", "warning"),
            ("partial", "info"),
            ("done", "success"),
            ("over done", "danger"),
        ):
            self.assertIn(
                repr(value).replace("'", ""),
                decorated[decoration].replace("'", ""),
                f"{value} must be the {decoration} badge, as in view_purchase_order_list",
            )
