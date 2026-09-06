from lxml import etree

from odoo.tests import tagged

from odoo.addons.base.tests.common import BaseCommon


@tagged("post_install", "-at_install")
class TestSaleOrderListViews(BaseCommon):
    """What the sales order lists let a user do to a whole selection."""

    def _list_root(self, xmlid):
        view = self.quick_ref(xmlid)
        arch = self.env["sale.order"].get_view(view.id, "list")["arch"]
        return etree.fromstring(arch)

    def test_the_order_list_allows_mass_editing(self):
        root = self._list_root("sale.view_sale_order_list")
        self.assertEqual(root.get("multi_edit"), "1")

    def test_the_quotation_list_keeps_mass_editing_through_inheritance(self):
        # Three views deep from `view_sale_order_list`, and the one the
        # Quotations menu actually opens: an heir dropping the attribute would
        # take mass editing away exactly where salespeople use it.
        root = self._list_root("sale.view_sale_order_list_quotation")
        self.assertEqual(root.get("multi_edit"), "1")
