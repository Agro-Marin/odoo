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
        expense_acc = self.env['account.account'].create({
            'name': 'Stock Expense', 'code': '600300', 'account_type': 'expense',
        })
        val_acc.account_stock_expense_id = expense_acc.id
        self.assertTrue(val_acc.account_stock_variation_id)

        day1 = fields.Datetime.now() - timedelta(days=5)
        day2 = fields.Datetime.now() - timedelta(days=3)
        day3 = fields.Datetime.now() - timedelta(days=1)

        # Period 1: receive 10 @ 10 -> value 100, close #1 posts to the valuation account.
        with freeze_time(day1):
            self._make_in_move(product, 10, unit_cost=10)
            company.action_close_stock_valuation(auto_post=True)
        self.assertEqual(sum(self._get_stock_valuation_move_lines().mapped('balance')), 100.0)

        # Period 2: receive 5 more @ 10 -> value +50 (not yet in accounting).
        with freeze_time(day2):
            self._make_in_move(product, 5, unit_cost=10)

        # Close #2 must recognise the +50 period variation in the expense account.
        with freeze_time(day3):
            action = company.action_close_stock_valuation(auto_post=True)
        move = self.env['account.move'].browse(action['res_id'])
        self.assertEqual(move.state, 'posted')

        expense_bal = sum(move.line_ids.filtered(lambda l: l.account_id == expense_acc).mapped('balance'))
        valuation_bal = sum(move.line_ids.filtered(lambda l: l.account_id == val_acc).mapped('balance'))
        # +50 stock increase -> expense credited 50 (reduced), valuation debited 50.
        self.assertEqual(expense_bal, -50.0, "period variation was not posted to the expense account")
        self.assertEqual(valuation_bal, 50.0)
        self.assertEqual(sum(move.line_ids.mapped('debit')), sum(move.line_ids.mapped('credit')))

    def test_get_last_in_is_company_scoped(self):
        """_get_last_in must not return another company's move."""
        move = self._make_in_move(self.product_fifo, 10, unit_cost=7)
        self.assertTrue(move.is_in)
        self.assertEqual(move.company_id, self.company)
        # Same company sees it...
        self.assertEqual(self.product_fifo.with_company(self.company).sudo()._get_last_in(), move)
        # ...a company with no receipt for the product does not.
        leaked = self.product_fifo.with_company(self.other_company).sudo()._get_last_in()
        self.assertFalse(leaked, "cross-company leak: _get_last_in returned another company's move")

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
        last = self.env['stock.avco.report'].search(
            [('product_id', '=', product.id), ('company_id', '=', self.company.id)]
        ).sorted(lambda r: (r.date, r.id))[-1]
        self.assertAlmostEqual(product.total_value, 300.0, places=2)
        self.assertAlmostEqual(last.total_value, product.total_value, places=2)
        self.assertAlmostEqual(last.avco_value, product.avg_cost, places=2)


class TestAvcoAccumulator(TransactionCase):
    """Pure unit tests for the shared AVCO recurrence — no ORM/database needed."""

    def test_regular_accumulation(self):
        acc = AvcoAccumulator()
        acc.add_in(10, 100)          # 10 @ 10
        self.assertEqual((acc.quantity, acc.value, acc.unit_cost), (10, 100, 10))
        acc.add_in(10, 200)          # +10 @ 20 -> avg 15
        self.assertEqual((acc.quantity, acc.value, acc.unit_cost), (20, 300, 15))
        removed = acc.add_out(5)     # -5 @ 15
        self.assertEqual(removed, 75)
        self.assertEqual((acc.quantity, acc.value, acc.unit_cost), (15, 225, 15))

    def test_recover_from_negative(self):
        acc = AvcoAccumulator(quantity=-5, value=-50, unit_cost=10)
        acc.add_in(10, 200)          # from negative: reset avg to incoming 20
        self.assertEqual(acc.unit_cost, 20)
        self.assertEqual(acc.quantity, 5)
        self.assertEqual(acc.value, 100)   # 20 * 5

    def test_manual_revaluation(self):
        acc = AvcoAccumulator(quantity=10, value=100, unit_cost=10)
        delta = acc.set_unit_cost(12)      # revalue 10 units 10 -> 12
        self.assertEqual(delta, 20)
        self.assertEqual((acc.value, acc.unit_cost), (120, 12))
