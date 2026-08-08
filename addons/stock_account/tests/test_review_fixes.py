# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Regression tests for valuation/closing correctness fixes.

Each test asserts the corrected behaviour and would fail on the pre-fix code:
  * continental period-variation posting nets the pending valuation true-up
    (res_company._get_continental_realtime_variation_vals extra_balance keying);
  * _get_last_in is scoped to the current company (no cross-company leak);
  * FIFO over-consumption extrapolates the last price in the product UoM.
"""

from datetime import timedelta

from freezegun import freeze_time

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.stock_account.models.avco import AvcoAccumulator
from odoo.addons.stock_account.tests.common import TestStockValuationCommon


@tagged("post_install", "-at_install")
class TestReviewFixes(TestStockValuationCommon):
    def test_continental_variation_nets_pending_true_up(self):
        """Continental perpetual close: the period variation posted to the expense
        account must reflect the just-computed valuation true-up (step 2). Before the
        fix, `extra_balance[account]` (record key on a defaultdict) returned 0, so the
        period variation was silently suppressed and the amount stayed parked in the
        stock variation account."""
        company = self.company
        product = self.product_standard_auto  # standard cost, real_time (perpetual)
        val_acc = self.account_stock_valuation
        expense_acc = self.env["account.account"].create(
            {
                "name": "Stock Expense",
                "code": "600300",
                "account_type": "expense",
            }
        )
        val_acc.account_stock_expense_id = expense_acc.id
        self.assertTrue(val_acc.account_stock_variation_id)

        day1 = fields.Datetime.now() - timedelta(days=5)
        day2 = fields.Datetime.now() - timedelta(days=3)
        day3 = fields.Datetime.now() - timedelta(days=1)

        # Period 1: receive 10 @ 10 -> value 100, close #1 posts to the valuation account.
        with freeze_time(day1):
            self._make_in_move(product, 10, unit_cost=10)
            company.action_close_stock_valuation(auto_post=True)
        self.assertEqual(
            sum(self._get_stock_valuation_move_lines().mapped("balance")), 100.0
        )

        # Period 2: receive 5 more @ 10 -> value +50 (not yet in accounting).
        with freeze_time(day2):
            self._make_in_move(product, 5, unit_cost=10)

        # Close #2 must recognise the +50 period variation in the expense account.
        with freeze_time(day3):
            action = company.action_close_stock_valuation(auto_post=True)
        move = self.env["account.move"].browse(action["res_id"])
        self.assertEqual(move.state, "posted")

        expense_bal = sum(
            move.line_ids.filtered(lambda l: l.account_id == expense_acc).mapped(
                "balance"
            )
        )
        valuation_bal = sum(
            move.line_ids.filtered(lambda l: l.account_id == val_acc).mapped("balance")
        )
        # +50 stock increase -> expense credited 50 (reduced), valuation debited 50.
        self.assertEqual(
            expense_bal, -50.0, "period variation was not posted to the expense account"
        )
        self.assertEqual(valuation_bal, 50.0)
        self.assertEqual(
            sum(move.line_ids.mapped("debit")), sum(move.line_ids.mapped("credit"))
        )

    def test_get_last_in_is_company_scoped(self):
        """_get_last_in must not return another company's move."""
        move = self._make_in_move(self.product_fifo, 10, unit_cost=7)
        self.assertTrue(move.is_in)
        self.assertEqual(move.company_id, self.company)
        # Same company sees it...
        self.assertEqual(
            self.product_fifo.with_company(self.company).sudo()._get_last_in(), move
        )
        # ...a company with no receipt for the product does not.
        leaked = (
            self.product_fifo.with_company(self.other_company).sudo()._get_last_in()
        )
        self.assertFalse(
            leaked, "cross-company leak: _get_last_in returned another company's move"
        )

    def test_fifo_oversell_extrapolation_uses_product_uom(self):
        """Over-consuming the FIFO stack extrapolates the last price per product UoM.
        Buy 1 'Pack of 6' @10/unit (=6 units, value 60); valuing 7 units must yield
        6*10 + 1*10 = 70 (pre-fix returned 120, dividing value by the pack qty)."""
        move = self._make_in_move(
            self.product_fifo, 1, unit_cost=10, uom_id=self.uom_pack_of_6.id
        )
        self.assertEqual(move._get_valued_qty(), 6)
        self.assertEqual(move.value, 60)
        self.assertEqual(self.product_fifo.qty_available, 6)
        self.assertEqual(self.product_fifo._run_fifo(7), 70)

    def test_avco_report_matches_engine(self):
        """The AVCO audit report reproduces the live valuation on real data (both now
        share AvcoAccumulator). Two receipts on distinct days give an unambiguous order:
        10@10 then 10@20 -> avg 15, value 300."""
        product = self.product_avco.with_company(self.company)
        day1 = fields.Datetime.now() - timedelta(days=2)
        day2 = fields.Datetime.now() - timedelta(days=1)
        with freeze_time(day1):
            self._make_in_move(product, 10, unit_cost=10)
        with freeze_time(day2):
            self._make_in_move(product, 10, unit_cost=20)

        # stock.avco.report is a SQL view over stock_move; flush so it sees the
        # freshly-written is_in/value columns.
        self.env.flush_all()
        last = (
            self.env["stock.avco.report"]
            .search(
                [("product_id", "=", product.id), ("company_id", "=", self.company.id)]
            )
            .sorted(lambda r: (r.date, r.id))[-1]
        )
        self.assertAlmostEqual(product.total_value, 300.0, places=2)
        self.assertAlmostEqual(last.total_value, product.total_value, places=2)
        self.assertAlmostEqual(last.avco_value, product.avg_cost, places=2)


class TestAvcoAccumulator(TransactionCase):
    """Pure unit tests for the shared AVCO recurrence — no ORM/database needed."""

    def test_regular_accumulation(self):
        acc = AvcoAccumulator()
        acc.add_in(10, 100)  # 10 @ 10
        self.assertEqual((acc.quantity, acc.value, acc.unit_cost), (10, 100, 10))
        acc.add_in(10, 200)  # +10 @ 20 -> avg 15
        self.assertEqual((acc.quantity, acc.value, acc.unit_cost), (20, 300, 15))
        removed = acc.add_out(5)  # -5 @ 15
        self.assertEqual(removed, 75)
        self.assertEqual((acc.quantity, acc.value, acc.unit_cost), (15, 225, 15))

    def test_recover_from_negative(self):
        acc = AvcoAccumulator(quantity=-5, value=-50, unit_cost=10)
        acc.add_in(10, 200)  # from negative: reset avg to incoming 20
        self.assertEqual(acc.unit_cost, 20)
        self.assertEqual(acc.quantity, 5)
        self.assertEqual(acc.value, 100)  # 20 * 5

    def test_manual_revaluation(self):
        acc = AvcoAccumulator(quantity=10, value=100, unit_cost=10)
        delta = acc.set_unit_cost(12)  # revalue 10 units 10 -> 12
        self.assertEqual(delta, 20)
        self.assertEqual((acc.value, acc.unit_cost), (120, 12))


@tagged("post_install", "-at_install")
class TestValuationAuditFixes(TestStockValuationCommon):
    """Regressions for the 2026-08-08 stock_account audit.

    Each test failed on the pre-fix code; the assertion messages name what broke.
    """

    def _make_other_company_receipt(self, product, quantity, unit_cost):
        """Receive `quantity` of `product` into `self.other_company`'s warehouse."""
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.other_company.id)], limit=1
        )
        env = self.env(
            context=dict(self.env.context, allowed_company_ids=self.other_company.ids)
        )
        move = env["stock.move"].create(
            {
                "product_id": product.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": warehouse.lot_stock_id.id,
                "product_uom_id": self.uom.id,
                "product_uom_qty": quantity,
                "picking_type_id": warehouse.in_type_id.id,
                "value_manual": unit_cost * quantity,
                "price_unit": unit_cost,
                "company_id": self.other_company.id,
            }
        )
        move._action_confirm()
        move._action_assign()
        move.picked = True
        move._action_done()
        return move, warehouse

    def test_quant_value_is_scoped_to_its_own_company(self):
        """`quant.value` divided the cross-company `total_value` by one company's
        quantity, so every company's quant reported the whole group's value."""
        product = self.product_avco
        self.env.user.company_ids = [(4, self.other_company.id)]
        self.category_avco.with_company(
            self.other_company
        ).property_cost_method = "average"
        self.env.flush_all()

        self._make_in_move(product, 10, unit_cost=10)  # company A: 100
        _move, other_warehouse = self._make_other_company_receipt(product, 5, 100)
        self.env.flush_all()
        self.env.invalidate_all()

        both = self.env(
            context=dict(
                self.env.context,
                allowed_company_ids=[self.company.id, self.other_company.id],
            )
        )
        quant_a = both["stock.quant"].search(
            [
                ("product_id", "=", product.id),
                ("location_id", "=", self.stock_location.id),
            ]
        )
        quant_b = both["stock.quant"].search(
            [
                ("product_id", "=", product.id),
                ("location_id", "=", other_warehouse.lot_stock_id.id),
            ]
        )
        self.assertAlmostEqual(quant_a.value, 100.0, places=2)
        self.assertAlmostEqual(quant_b.value, 500.0, places=2)
        # `total_value` stays the deliberate cross-company aggregate.
        self.assertAlmostEqual(
            both["product.product"].browse(product.id).total_value, 600.0, places=2
        )

    def test_unpicking_a_done_move_revalues_it(self):
        """`picked` decides whether a move is valued, so it must trigger a
        revaluation like the owner and the locations do."""
        move = self._make_in_move(self.product_avco, 10, unit_cost=10)
        self.env.flush_all()
        self.assertTrue(move.is_in)
        self.assertEqual(move.value, 100.0)

        move.picked = False  # stored, writable, and editable on a done picking
        self.env.flush_all()
        move.invalidate_recordset()

        self.assertEqual(move._get_valued_qty(), 0)
        self.assertFalse(move.is_in, "stored is_in kept describing picked lines")
        self.assertEqual(move.value, 0.0, "a move no longer valued kept its value")

    def test_avco_at_date_keeps_the_historical_cost(self):
        """`_get_value_from_std_price` had no historical branch for `average`, so a
        later cost change restated what the stock had been worth."""
        product = self.product_avco.with_company(self.company)
        day5 = fields.Datetime.now() - timedelta(days=5)
        with freeze_time(day5):
            # No value_manual/price_unit: the move falls through to the product cost.
            move = self.env["stock.move"].create(
                {
                    "product_id": product.id,
                    "location_id": self.supplier_location.id,
                    "location_dest_id": self.stock_location.id,
                    "product_uom_id": self.uom.id,
                    "product_uom_qty": 10,
                    "picking_type_id": self.picking_type_in.id,
                }
            )
            move._action_confirm()
            move._action_assign()
            move.picked = True
            move._action_done()
        self.env.flush_all()
        self.assertEqual(move.value, 100.0)

        product.standard_price = 30.0
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertAlmostEqual(
            product.with_context(to_date=day5).total_value, 100.0, places=2
        )

    def test_product_level_revaluation_updates_the_cost(self):
        """A product-level `product.value` reached the engine but not
        `standard_price`, which is what prices out moves, COGS and margins."""
        product = self.product_avco.with_company(self.company)
        self._make_in_move(product, 10, unit_cost=10)
        self.env.flush_all()
        self.assertEqual(product.standard_price, 10.0)

        self.env["product.value"].create(
            {
                "product_id": product.id,
                "value": 25.0,
                "company_id": self.company.id,
            }
        )
        self.env.flush_all()
        product.invalidate_recordset()

        self.assertAlmostEqual(product.avg_cost, 25.0, places=2)
        self.assertAlmostEqual(product.standard_price, 25.0, places=2)

    def test_lot_level_revaluation_reaches_the_lot(self):
        """The lot-level branch recomputed the product but never the lot."""
        product = self.product_avco
        product.lot_valuated = True
        lot = self.env["stock.lot"].create(
            {"name": "RV1", "product_id": product.id, "company_id": self.company.id}
        )
        self._make_in_move(product, 10, unit_cost=10, lot_ids=[lot])
        self.env.flush_all()

        self.env["product.value"].create(
            {
                "product_id": product.id,
                "lot_id": lot.id,
                "value": 25.0,
                "company_id": self.company.id,
            }
        )
        self.env.flush_all()
        lot.invalidate_recordset()
        self.assertAlmostEqual(lot.standard_price, 25.0, places=2)

    def test_emptied_fifo_lot_keeps_its_cost_basis(self):
        """`_run_fifo_batch` published a hard 0 for a zero quantity where the
        standard and average paths both preserve the cost."""
        product = self.product_fifo
        product.lot_valuated = True
        lot = self.env["stock.lot"].create(
            {"name": "FB1", "product_id": product.id, "company_id": self.company.id}
        )
        self._make_in_move(product, 10, unit_cost=7, lot_ids=[lot])
        self._make_out_move(product, 10, lot_ids=[lot])
        self.env.flush_all()
        lot.invalidate_recordset()
        self.assertEqual(lot.product_qty, 0.0)

        self.env["stock.lot"].browse(lot.id)._update_standard_price()
        self.env.flush_all()
        lot.invalidate_recordset()
        self.assertEqual(lot.standard_price, 7.0)

    def test_closing_cron_survives_a_quiet_company(self):
        """The cron went through the UI action, whose `UserError` for "nothing to
        close" aborted the run and rolled back the closings already computed."""
        self.env["res.company"].search([]).write(
            {"inventory_period": "daily", "inventory_valuation": "periodic"}
        )
        self._make_in_move(self.product_avco, 10, unit_cost=10)
        self.env.flush_all()
        self.env["res.company"]._cron_post_stock_valuation()  # must not raise

    def test_missing_valuation_account_raises_user_error(self):
        """An unset stock valuation account reached the database as NULL and came
        back as a check-constraint violation that poisoned the transaction."""
        self._use_inventory_location_accounting()
        self.category_avco_auto.property_stock_valuation_account_id = False
        self.company.account_stock_valuation_id = False
        self.env.flush_all()
        self.assertFalse(
            self.product_avco_auto._get_product_accounts()["stock_valuation"]
        )
        with self.assertRaises(UserError):
            self._make_out_move(
                self.product_avco_auto,
                1,
                location_dest_id=self.inventory_location.id,
            )

    def test_adjust_valuation_is_not_offered_without_create_rights(self):
        """The server action was bound with no group while `product.value` create
        is stock-manager only, so accounting users got a dialog that always
        failed."""
        account_user = self._create_new_internal_user(
            name="Audit Acc",
            login="audit_acc_user",
            groups="account.group_account_invoice",
        )
        account_user.company_ids = [(4, self.company.id)]
        account_user.company_id = self.company
        env_user = self.env(user=account_user)
        bindings = env_user["ir.actions.actions"].get_bindings("stock.move")
        offered = [action.get("name") for action in bindings.get("action", [])]
        self.assertNotIn("Adjust Valuation", offered)
        self.assertFalse(env_user["product.value"].has_access("create"))

    def test_is_valued_internal_search_matches_compute(self):
        """The search scoped to `env.companies` while the compute did not, so the
        field answered differently depending on the session."""
        location = self.env["stock.location"].search(
            [("company_id", "=", self.other_company.id), ("usage", "=", "internal")],
            limit=1,
        )
        env_a = self.env(
            context=dict(self.env.context, allowed_company_ids=self.company.ids)
        )
        computed = bool(env_a["stock.location"].browse(location.id).is_valued_internal)
        found = bool(
            env_a["stock.location"].search(
                [("id", "=", location.id), ("is_valued_internal", "=", True)]
            )
        )
        self.assertEqual(computed, found)

    def test_is_valued_follows_the_flags_it_reads(self):
        """`is_valued` reads is_in/is_out but depended on neither."""
        move = self._make_in_move(self.product_avco, 10, unit_cost=10)
        self.env.flush_all()
        self.assertTrue(move.is_valued)
        move.move_line_ids.owner_id = self.owner.id
        self.env.flush_all()
        self.assertFalse(move.is_in)
        self.assertFalse(move.is_valued)

    def test_category_stock_journal_is_used(self):
        """`_create_account_move` read the journal off the company, so a
        category-level `property_stock_journal` was silently dropped."""
        journal = self.env["account.journal"].create(
            {
                "name": "Category Stock Journal",
                "code": "CSTJ",
                "type": "general",
                "company_id": self.company.id,
            }
        )
        self.category_avco_auto.property_stock_journal = journal.id
        self._use_inventory_location_accounting()
        self.env.flush_all()

        self._make_in_move(self.product_avco_auto, 10, unit_cost=10)
        move = self._make_out_move(
            self.product_avco_auto, 2, location_dest_id=self.inventory_location.id
        )
        self.env.flush_all()
        self.assertTrue(move.account_move_id)
        self.assertEqual(move.account_move_id.journal_id, journal)

    def test_both_accounted_locations_reach_the_entry(self):
        """Only the source branch ran, so the destination's valuation account was
        dropped from the entry without a word."""
        source_account = self.env["account.account"].create(
            {"name": "Loc Src", "code": "100201", "account_type": "asset_current"}
        )
        dest_account = self.env["account.account"].create(
            {"name": "Loc Dst", "code": "100202", "account_type": "asset_current"}
        )
        source = self.env["stock.location"].create(
            {
                "name": "Accounted Source",
                "usage": "internal",
                "location_id": self.stock_location.id,
                "company_id": self.company.id,
                "valuation_account_id": source_account.id,
            }
        )
        destination = self.env["stock.location"].create(
            {
                "name": "Accounted Destination",
                "usage": "inventory",
                "company_id": self.company.id,
                "valuation_account_id": dest_account.id,
            }
        )
        self.env.flush_all()

        self._make_in_move(
            self.product_avco_auto, 10, unit_cost=10, location_dest_id=source.id
        )
        move = self._make_out_move(
            self.product_avco_auto,
            3,
            location_id=source.id,
            location_dest_id=destination.id,
        )
        self.env.flush_all()
        accounts = move.account_move_id.line_ids.account_id
        self.assertIn(dest_account, accounts)
        self.assertIn(source_account, accounts)

    def test_price_history_is_stamped_with_the_writing_company(self):
        """`standard_price` is company-dependent, so a row stamped with
        `product.company_id` was invisible to the company that wrote the price."""
        product = self.env["product.product"].create(
            {
                "name": "Branch Cost Product",
                "is_storable": True,
                "uom_id": self.uom.id,
                "categ_id": self.category_avco.id,
                "company_id": self.branch.id,
            }
        )
        self.env.flush_all()

        parent_scoped = product.with_company(self.company)
        parent_scoped.standard_price = 55.0
        self.env.flush_all()

        self.assertTrue(
            parent_scoped._get_last_product_value(),
            "the price history row is invisible to the company that wrote it",
        )

    def test_remaining_qty_is_in_the_product_uom(self):
        """`_get_remaining_moves` mixed two units of measure in one mapping: the
        bottom-of-stack move got `_run_fifo_get_stack`'s product-UoM figure and
        every other move got its own `quantity`. `_compute_remaining_value` then
        divided one by the other."""
        product = self.product_fifo.with_company(self.company)
        day1 = fields.Datetime.now() - timedelta(days=2)
        day2 = fields.Datetime.now() - timedelta(days=1)
        with freeze_time(day1):
            first = self._make_in_move(
                product, 1, unit_cost=10, uom_id=self.uom_pack_of_6.id
            )
        with freeze_time(day2):
            second = self._make_in_move(
                product, 1, unit_cost=10, uom_id=self.uom_pack_of_6.id
            )
        self._make_out_move(product, 3)
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(product.qty_available, 9.0)

        # 9 units left: 3 of the first pack, all 6 of the second.
        self.assertAlmostEqual(first.remaining_qty, 3.0, places=2)
        self.assertAlmostEqual(second.remaining_qty, 6.0, places=2)
        self.assertAlmostEqual(first.remaining_value, 30.0, places=2)
        self.assertAlmostEqual(second.remaining_value, 60.0, places=2)
