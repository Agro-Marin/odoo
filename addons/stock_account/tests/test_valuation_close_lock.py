from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.stock_account.tests.common import TestStockValuationCommon


@tagged("post_install", "-at_install")
class TestValuationCloseLock(TestStockValuationCommon):
    """Two closings of one company would book its period twice.

    The draft-closing logic guards against that only for entries it can see. Two
    callers running together each read a snapshot with no pending draft, and one
    `account.move` INSERT does not conflict with another, so nothing in the
    database stops them.
    """

    def _held_elsewhere(self):
        # A second cursor cannot see a company this transaction has not
        # committed, so the lock stands in for what SKIP LOCKED returns when
        # another closing holds the row.
        self.patch(
            self.registry["res.company"],
            "try_lock_for_update",
            lambda records, **kwargs: records.browse(),
        )

    def test_a_second_closing_is_refused_while_one_is_running(self):
        self._held_elsewhere()

        with self.assertRaises(UserError):
            self.company._close_stock_valuation()

    def test_the_button_refuses_too(self):
        # Matched on the message, not merely on UserError: a company with nothing
        # to close raises one of those anyway, so `assertRaises` alone passed
        # with the lock removed and proved nothing.
        self._held_elsewhere()

        with self.assertRaisesRegex(UserError, "already running"):
            self.company.action_close_stock_valuation()

    def test_the_cron_skips_a_company_being_closed_rather_than_failing(self):
        # The cron already wraps each company in a savepoint and catches
        # UserError, so a contended company is skipped and the rest still close.
        # Real stock first: with nothing to close, no entry is created either
        # way and the assertion below holds whether or not the lock is there.
        product = self.product_avco.with_company(self.company)
        self._make_in_move(product, 10, unit_cost=10)
        self.company.inventory_period = "daily"
        self.company.inventory_valuation = "periodic"
        self._held_elsewhere()

        self.env["res.company"]._cron_post_stock_valuation()

        self.assertFalse(
            self.env["account.move"].search(
                [
                    ("is_stock_valuation_closing", "=", True),
                    ("company_id", "=", self.company.id),
                ]
            ),
            "nothing may be booked for a company another closing holds",
        )

    def test_an_uncontended_closing_still_runs(self):
        product = self.product_avco.with_company(self.company)
        self._make_in_move(product, 10, unit_cost=10)

        self.company.action_close_stock_valuation(auto_post=True)

        self.assertTrue(
            self.env["account.move"].search(
                [
                    ("is_stock_valuation_closing", "=", True),
                    ("company_id", "=", self.company.id),
                ]
            ),
            "the lock must not stop an ordinary closing",
        )
