import json

import odoo

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@odoo.tests.tagged("post_install", "-at_install")
class TestPosDashboardGraph(TestPoSCommon):
    """The kanban card carries a week of sales, so a manager reads the trend
    without opening the config."""

    def setUp(self):
        super().setUp()
        self.config = self.basic_config

    def _graph(self, config):
        return json.loads(config.kanban_dashboard_graph)[0]

    def test_graph_is_seven_days_of_sample_data_without_orders(self):
        graph = self._graph(self.config)
        self.assertTrue(graph["is_sample_data"])
        self.assertEqual(len(graph["values"]), 7)
        self.assertEqual([point["y"] for point in graph["values"]], [0] * 7)

    def test_graph_sums_paid_orders_of_the_day(self):
        product = self.create_product("Product 1", self.categ_basic, 150)
        self.open_new_session()
        session = self.pos_session
        for amount in (150, 250):
            order = self.env["pos.order"].create(
                {
                    "session_id": session.id,
                    "lines": [
                        (
                            0,
                            0,
                            {
                                "name": "OL/0001",
                                "product_id": product.id,
                                "price_unit": amount,
                                "discount": 0,
                                "qty": 1.0,
                                "price_subtotal": amount,
                                "price_subtotal_incl": amount,
                            },
                        )
                    ],
                    "amount_total": amount,
                    "amount_tax": 0.0,
                    "amount_paid": 0.0,
                    "amount_return": 0.0,
                }
            )
            order.state = "paid"

        self.config.invalidate_recordset(["kanban_dashboard_graph"])
        graph = self._graph(self.config)
        self.assertFalse(graph["is_sample_data"])
        self.assertEqual(len(graph["values"]), 7)
        # Today is the last of the seven points.
        self.assertEqual(graph["values"][-1]["y"], 400.0)
        self.assertEqual([point["y"] for point in graph["values"][:-1]], [0] * 6)

    def test_graph_ignores_draft_and_cancelled_orders(self):
        product = self.create_product("Product 1", self.categ_basic, 150)
        self.open_new_session()
        session = self.pos_session
        for state in ("draft", "cancel"):
            order = self.env["pos.order"].create(
                {
                    "session_id": session.id,
                    "lines": [
                        (
                            0,
                            0,
                            {
                                "name": "OL/0001",
                                "product_id": product.id,
                                "price_unit": 150,
                                "discount": 0,
                                "qty": 1.0,
                                "price_subtotal": 150,
                                "price_subtotal_incl": 150,
                            },
                        )
                    ],
                    "amount_total": 150.0,
                    "amount_tax": 0.0,
                    "amount_paid": 0.0,
                    "amount_return": 0.0,
                }
            )
            order.state = state

        self.config.invalidate_recordset(["kanban_dashboard_graph"])
        self.assertTrue(self._graph(self.config)["is_sample_data"])
