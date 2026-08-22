import logging

import odoo

from odoo.addons.point_of_sale.tests.common import TestPoSCommon

_logger = logging.getLogger(__name__)


@odoo.tests.tagged("post_install", "-at_install")
class TestAuditVerification3(TestPoSCommon):

    def setUp(self):
        super().setUp()
        self.config = self.basic_config
        self.product = self.create_product("AuditProd3", self.categ_basic, 100, 50)

    def test_A1_is_refund_order_both_branches(self):
        self._start_pos_session(self.cash_pm1, 0)
        orders = self._create_orders(
            [
                {
                    "pos_order_lines_ui_args": [(self.product, 1)],
                    "payments": [(self.cash_pm1, 100)],
                    "uuid": "audit-a1-normal",
                },
                {
                    "pos_order_lines_ui_args": [(self.product, -1)],
                    "payments": [(self.cash_pm1, -100)],
                    "uuid": "audit-a1-neg",
                },
            ]
        )
        normal = orders["audit-a1-normal"]
        neg = orders["audit-a1-neg"]

        self.assertFalse(normal.is_refund)
        self.assertGreater(normal.amount_total, 0)
        self.assertFalse(normal._is_refund_order())

        normal.is_refund = True
        self.assertTrue(normal._is_refund_order())
        normal.is_refund = False
        self.assertFalse(normal._is_refund_order())

        _logger.info("A1 neg order amount_total=%s", neg.amount_total)
        self.assertFalse(neg.is_refund)
        self.assertLess(neg.amount_total, 0)
        self.assertTrue(neg._is_refund_order())

    def test_A1b_is_refund_order_is_singleton(self):
        self._start_pos_session(self.cash_pm1, 0)
        orders = self._create_orders(
            [
                {
                    "pos_order_lines_ui_args": [(self.product, 1)],
                    "payments": [(self.cash_pm1, 100)],
                    "uuid": "audit-a1b-1",
                },
                {
                    "pos_order_lines_ui_args": [(self.product, 1)],
                    "payments": [(self.cash_pm1, 100)],
                    "uuid": "audit-a1b-2",
                },
            ]
        )
        recs = orders["audit-a1b-1"] | orders["audit-a1b-2"]
        with self.assertRaises(ValueError):
            recs._is_refund_order()

    def test_A2_search_paid_order_ids_count_matches_same_currency(self):
        self._start_pos_session(self.cash_pm1, 0)
        self._create_orders(
            [
                {
                    "pos_order_lines_ui_args": [(self.product, 1)],
                    "payments": [(self.cash_pm1, 100)],
                    "uuid": "audit-a2-%02d" % i,
                }
                for i in range(3)
            ]
        )
        result = self.env["pos.order"].search_paid_order_ids(self.config.id, [], 100, 0)
        _logger.info("A2 result=%r", result)
        self.assertEqual(result["totalCount"], 3)
        self.assertEqual(len(result["ordersInfo"]), 3)
        returned_ids = [oid for oid, _date in result["ordersInfo"]]
        orders = self.env["pos.order"].browse(returned_ids)
        self.assertTrue(all(o.currency_id == self.config.currency_id for o in orders))
