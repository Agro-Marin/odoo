import logging

import odoo

from odoo.addons.point_of_sale.tests.common import TestPoSCommon

_logger = logging.getLogger(__name__)


@odoo.tests.tagged("post_install", "-at_install")
class TestAuditVerification3(TestPoSCommon):
    """Round-3 audit: direct unit coverage for refactors that removed
    duplicated business predicates (the riskiest of which drive tax/quantity
    signs). These call model methods directly with minimal inputs — the style
    the surrounding suite lacks (it reaches this logic only through full
    session-close integration or browser tours)."""

    def setUp(self):
        super().setUp()
        self.config = self.basic_config
        self.product = self.create_product("AuditProd3", self.categ_basic, 100, 50)

    # ---- A1 refund-order predicate: single source of truth for the sign rule ----
    def test_A1_is_refund_order_both_branches(self):
        """`pos.order._is_refund_order()` must fire on EITHER the explicit
        ``is_refund`` flag OR a negative net total. The negative-total path used
        to be re-spelled inline at four call sites; three sibling sites used the
        bare ``is_refund`` flag, so a value-identical order could be classified
        differently depending on which code path touched it."""
        self._start_pos_session(self.cash_pm1, 0)
        orders = self._create_orders(
            [
                {
                    "pos_order_lines_ui_args": [(self.product, 1)],
                    "payments": [(self.cash_pm1, 100)],
                    "uuid": "audit-a1-normal",
                },
                {
                    # Negative total, but NOT flagged is_refund. The amount
                    # branch must still classify it as a refund.
                    "pos_order_lines_ui_args": [(self.product, -1)],
                    "payments": [(self.cash_pm1, -100)],
                    "uuid": "audit-a1-neg",
                },
            ]
        )
        normal = orders["audit-a1-normal"]
        neg = orders["audit-a1-neg"]

        # Positive, unflagged → not a refund.
        self.assertFalse(normal.is_refund)
        self.assertGreater(normal.amount_total, 0)
        self.assertFalse(normal._is_refund_order())

        # Flag branch: is_refund True even though the total is non-negative.
        normal.is_refund = True
        self.assertTrue(normal._is_refund_order())
        normal.is_refund = False
        self.assertFalse(normal._is_refund_order())

        # Amount branch: negative total, is_refund False → still a refund.
        _logger.info("A1 neg order amount_total=%s", neg.amount_total)
        self.assertFalse(neg.is_refund)
        self.assertLess(neg.amount_total, 0)
        self.assertTrue(neg._is_refund_order())

    def test_A1b_is_refund_order_is_singleton(self):
        """It is a per-order property; calling on a multi-record set must raise
        rather than silently read the first record (a latent bug pattern this
        module was audited for)."""
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

    # ---- A2 search_paid_order_ids: totalCount / results consistency ----
    def test_A2_search_paid_order_ids_count_matches_same_currency(self):
        """Characterization test for the paginated order lookup that drives the
        ticket-screen "load more". In a single-currency config the post-search
        currency filter is a no-op, so ``totalCount`` must equal the number of
        returned orders. This pins the contract the frontend relies on and
        documents that the count is computed on the pre-currency-filter domain
        (a real divergence only a multi-currency config can trigger)."""
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
        # Every returned order id belongs to this config (or a trusted one).
        returned_ids = [oid for oid, _date in result["ordersInfo"]]
        orders = self.env["pos.order"].browse(returned_ids)
        self.assertTrue(all(o.currency_id == self.config.currency_id for o in orders))
