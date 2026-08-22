import logging

from odoo import fields
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import CommonPosTest

_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install")
class TestPosOrderLookup(CommonPosTest):
    def setUp(self):
        super().setUp()
        self.pos_config_usd.open_ui()
        self.session = self.pos_config_usd.current_session_id
        self.product = self.env["product.product"].search(
            [("available_in_pos", "=", True)], limit=1
        )

    def _create_order(self, *, with_line=True, state="paid"):
        order = self.env["pos.order"].create(
            {
                "session_id": self.session.id,
                "state": state,
                "amount_tax": 0,
                "amount_total": 0,
                "amount_paid": 0,
                "amount_return": 0,
            }
        )
        if with_line:
            self.env["pos.order.line"].create(
                {
                    "order_id": order.id,
                    "product_id": self.product.id,
                    "qty": 1,
                    "price_unit": 0,
                    "price_subtotal": 0,
                    "price_subtotal_incl": 0,
                }
            )
        return order

    def _lookup(self, limit=100, offset=0, domain=None):
        return self.env["pos.order"].search_paid_order_ids(
            self.pos_config_usd.id, domain or [], limit, offset
        )

    def test_order_without_lines_is_listed(self):
        order = self._create_order(with_line=False)
        result = self._lookup()
        self.assertIn(order.id, [oid for oid, _date in result["ordersInfo"]])

    def test_count_matches_the_listing(self):
        self._create_order(with_line=False)
        self._create_order(with_line=True)
        result = self._lookup()
        self.assertEqual(len(result["ordersInfo"]), result["totalCount"])

    def test_every_listed_order_carries_a_date(self):
        self._create_order(with_line=False)
        self._create_order(with_line=True)
        for _order_id, last_write in self._lookup()["ordersInfo"]:
            self.assertTrue(last_write)

    def test_a_full_page_is_full(self):
        for _i in range(5):
            self._create_order()
        result = self._lookup(limit=3)
        self.assertEqual(len(result["ordersInfo"]), 3)
        self.assertEqual(result["totalCount"], 5)

    def test_pages_do_not_overlap_or_skip(self):
        created = {self._create_order().id for _i in range(5)}
        first = self._lookup(limit=3, offset=0)["ordersInfo"]
        second = self._lookup(limit=3, offset=3)["ordersInfo"]
        paged = [oid for oid, _d in first] + [oid for oid, _d in second]
        self.assertEqual(len(paged), len(set(paged)))
        self.assertEqual(set(paged), created)

    def test_page_is_in_query_order(self):
        for _i in range(3):
            self._create_order()
        result = self._lookup()
        listed = [oid for oid, _d in result["ordersInfo"]]
        expected = self.env["pos.order"].search(
            [("config_id", "=", self.pos_config_usd.id), ("state", "=", "paid")],
            order="create_date desc",
        ).ids
        self.assertEqual(listed, expected)

    def test_draft_and_cancelled_orders_are_excluded(self):
        draft = self._create_order(state="draft")
        result = self._lookup()
        self.assertNotIn(draft.id, [oid for oid, _d in result["ordersInfo"]])

    def test_line_write_advances_the_stamp(self):
        order = self._create_order()
        before = dict(self._lookup()["ordersInfo"])[order.id]
        order.lines.write({"customer_note": "extra ketchup"})
        after = dict(self._lookup()["ordersInfo"])[order.id]
        self.assertGreaterEqual(after, before)
        self.assertEqual(after, order.lines.write_date)

    def test_stamp_falls_back_to_the_order_itself(self):
        order = self._create_order(with_line=False)
        self.assertEqual(
            dict(self._lookup()["ordersInfo"])[order.id],
            order.write_date,
        )

    def test_refunded_order_is_stamped_by_its_refund(self):
        order = self._create_order()
        refund = self._create_order(with_line=False)
        self.env["pos.order.line"].create(
            {
                "order_id": refund.id,
                "product_id": self.product.id,
                "qty": -1,
                "price_unit": 0,
                "price_subtotal": 0,
                "price_subtotal_incl": 0,
                "refunded_orderline_id": order.lines.id,
            }
        )
        stamps = dict(self._lookup()["ordersInfo"])
        self.assertIn(order.id, stamps)
        self.assertIn(refund.id, stamps)
        self.assertGreaterEqual(stamps[order.id], order.write_date)

    def test_domain_is_honoured(self):
        wanted = self._create_order()
        wanted.write({"tracking_number": "LOOKUP-ME"})
        self._create_order()
        result = self._lookup(domain=[("tracking_number", "=", "LOOKUP-ME")])
        self.assertEqual([oid for oid, _d in result["ordersInfo"]], [wanted.id])
        self.assertEqual(result["totalCount"], 1)

    def test_no_orders_is_an_empty_page(self):
        result = self._lookup()
        self.assertEqual(result["ordersInfo"], [])
        self.assertEqual(result["totalCount"], 0)

    def test_stamps_are_datetimes(self):
        order = self._create_order()
        stamp = dict(self._lookup()["ordersInfo"])[order.id]
        self.assertEqual(stamp, fields.Datetime.to_datetime(stamp))
