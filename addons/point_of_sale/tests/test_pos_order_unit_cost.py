from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install", "pos_order_cost")
class TestPosOrderLineCost(TestPoSCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.avco_product = cls.create_product(
            "AVCO Product",
            cls.categ_basic,
            10.0,
            standard_price=5.0,
        )
        cls.avco_product.categ_id.property_cost_method = "average"

    def test_price_cost_is_the_unit_cost_for_several_fifo_avco_lines(self):
        self.open_new_session()
        order = self._create_orders(
            [
                {
                    "pos_order_lines_ui_args": [
                        (self.avco_product, 2),
                        (self.avco_product, 3),
                    ],
                    "payments": [(self.cash_pm1, 50)],
                    "uuid": "00100-010-0001",
                }
            ]
        )["00100-010-0001"]

        self.assertEqual(len(order.lines), 2, "a per-line branch needs two lines")
        self.pos_session.action_pos_session_closing_control()

        for line in order.lines:
            self.assertTrue(line.is_total_cost_computed)
            self.assertAlmostEqual(
                line.price_cost,
                line.total_cost / line.qty,
                places=2,
                msg="price_cost is the unit cost behind total_cost",
            )
