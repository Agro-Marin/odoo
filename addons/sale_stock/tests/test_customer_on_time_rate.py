from odoo.tests import tagged

from .common import TestSaleStockCommon


@tagged("post_install", "-at_install")
class TestCustomerOnTimeRate(TestSaleStockCommon):
    def test_no_data_yields_negative_sentinel(self):
        partner = self.env["res.partner"].create({"name": "No history partner"})
        self.assertEqual(partner.customer_on_time_rate, -1)
