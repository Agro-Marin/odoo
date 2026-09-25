from odoo.tests import tagged

from odoo.addons.trade_product_matrix.tests.common import OrderProductMatrixCase


@tagged("post_install", "-at_install")
class TestPurchaseOrderGrid(OrderProductMatrixCase):
    order_model = "purchase.order"
    conflict_message = "multiple purchase lines"

    def test_report_prints_every_configurable_template(self):
        order = self._order()
        self._apply(order, (("S", "Red"), 2), (("M", "Blue"), 3))
        matrixes = order.get_report_matrixes()
        self.assertEqual(len(matrixes), 1)
        self.assertEqual(len(matrixes[0]["matrix"]), 2)

    def test_matrix_hides_extra_prices(self):
        self._ptavs("M").price_extra = 7
        header = self._order()._get_matrix(self.template)["header"]
        self.assertFalse(any("price" in cell for cell in header[1:]))
