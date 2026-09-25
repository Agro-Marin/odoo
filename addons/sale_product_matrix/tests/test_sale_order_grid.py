from odoo.tests import tagged

from odoo.addons.trade_product_matrix.tests.common import OrderProductMatrixCase


@tagged("post_install", "-at_install")
class TestSaleOrderGrid(OrderProductMatrixCase):
    order_model = "sale.order"
    conflict_message = "multiple sale lines"

    def test_report_prints_only_grid_entry_templates(self):
        order = self._order()
        self._apply(order, (("S", "Red"), 2), (("M", "Blue"), 3))
        self.template.product_add_mode = "configurator"
        self.assertEqual(order.get_report_matrixes(), [])
        self.template.product_add_mode = "matrix"
        self.assertEqual(len(order.get_report_matrixes()), 1)

    def test_matrix_shows_extra_prices(self):
        self._ptavs("M").price_extra = 7
        header = self._order()._get_matrix(self.template)["header"]
        self.assertIn(7.0, [cell.get("price") for cell in header[1:]])
