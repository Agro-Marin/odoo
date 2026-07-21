# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
from datetime import date

import odoo

from odoo.addons.point_of_sale.tests.common import TestPoSCommon

_logger = logging.getLogger(__name__)


@odoo.tests.tagged("post_install", "-at_install")
class TestPosClosingRounding(TestPoSCommon):
    """Rounding/date regressions in the session closing entry.

    Both defects are silent: they do not raise, they produce a wrong ledger.
    The FX one forces the cashier through Force Close and fabricates a
    "Difference at closing PoS session" plug line for money that was never
    lost; the date one back-dates the cash-difference statement line.
    """

    def setUp(self):
        super().setUp()
        self.config = self.other_currency_config

    def _set_session_rate(self, rate):
        """Rate of `other_currency` against the company currency."""
        self.other_currency.rate_ids.unlink()
        self.env["res.currency.rate"].create(
            {
                "rate": rate,
                "currency_id": self.other_currency.id,
                "name": date(2026, 1, 1),
            }
        )

    def _make_products(self, prices):
        """Four products on four distinct income accounts, at fixed prices.

        Distinct income accounts mean distinct sale keys, hence four separate
        debit-side accumulators each rounding independently, while the payment
        side aggregates into a single receivable accumulator. That asymmetry is
        what makes the per-contribution rounding error fail to cancel.

        The prices are pinned on the session pricelist rather than derived from
        the company-currency sales price: a derived price converts back exactly
        and would hide the defect.
        """
        products = []
        items = self.env["product.pricelist.item"]
        for i, price in enumerate(prices):
            account = self.env["account.account"].create(
                {
                    "name": f"PoS Income {i}",
                    "code": f"POSINC{i}",
                    "account_type": "income",
                    "company_ids": [(6, 0, self.company.ids)],
                }
            )
            product = self.create_product(
                f"RoundProd{i}",
                self.categ_basic,
                price,
                0.0,
                sale_account=account,
            )
            products.append(product)
            items |= items.create(
                {
                    "product_tmpl_id": product.product_tmpl_id.id,
                    "fixed_price": price,
                }
            )
        pricelist = self.config.pricelist_id
        pricelist.write({"item_ids": [(6, 0, (pricelist.item_ids | items).ids)]})
        return products

    def _close_and_get_move(self, session, bank_pm, products, order_count, prefix):
        # Prices come from the session pricelist, i.e. already in session
        # currency; the payment must match or the order is not "fully paid".
        total = sum(
            self.pricelist._get_product_price(product, 1) for product in products
        )
        self._create_orders(
            [
                {
                    "pos_order_lines_ui_args": [(product, 1) for product in products],
                    "payments": [(bank_pm, total)],
                    "customer": self.customer,
                    "uuid": f"{prefix}-{i}",
                }
                for i in range(order_count)
            ]
        )
        session.with_company(self.company).with_context(
            check_move_validity=False, skip_invoice_sync=True
        )._create_account_move(False, 0, {})
        return session.move_id

    def _imbalance(self, move):
        lines = move.line_ids
        return round(
            sum(lines.mapped("debit")) - sum(lines.mapped("credit")),
            self.company_currency.decimal_places,
        )

    def test_closing_entry_balances_at_non_exact_rate(self):
        """The regression: session currency at a rate that is not an exact
        divisor. Pre-fix `_update_amounts` discards the tax engine's already
        correct `balance` and re-derives it with a per-contribution FX
        conversion, so debit and credit drift apart and the move cannot post.
        """
        self._set_session_rate(0.63)
        products = self._make_products([1.0, 1.0, 1.0, 1.0])
        session = self._start_pos_session(self.cash_pm2 | self.bank_pm2, 0)
        move = self._close_and_get_move(session, self.bank_pm2, products, 80, "round")
        imbalance = self._imbalance(move)
        _logger.info("non-exact rate 0.63: imbalance %s", imbalance)
        self.assertEqual(
            imbalance,
            0.0,
            "closing entry is unbalanced in company currency: the debit and "
            "credit sides went through a different number of FX roundings",
        )

    def test_closing_entry_balances_at_exact_rate(self):
        """Control: a rate that divides exactly never exposed the defect."""
        self._set_session_rate(0.5)
        products = self._make_products([1.0, 1.0, 1.0, 1.0])
        session = self._start_pos_session(self.cash_pm2 | self.bank_pm2, 0)
        move = self._close_and_get_move(session, self.bank_pm2, products, 80, "exact")
        self.assertEqual(self._imbalance(move), 0.0)

    def test_closing_entry_balances_in_company_currency(self):
        """Control: same-currency session, no conversion involved at all."""
        self.config = self.basic_config
        products = self._make_products([1.0, 1.0, 1.0, 1.0])
        session = self._start_pos_session(self.cash_pm1 | self.bank_pm1, 0)
        move = self._close_and_get_move(session, self.bank_pm1, products, 20, "same")
        self.assertEqual(self._imbalance(move), 0.0)

    def test_statement_difference_uses_last_cash_movement(self):
        """The cash-difference line must be dated from the *last* cash movement.

        `account.bank.statement.line._order` is `internal_index desc`, so the
        old `sorted()[-1:]` picked the oldest line instead of the newest.
        """
        self.config = self.basic_config
        session = self._start_pos_session(self.cash_pm1, 0)
        dates = [date(2026, 7, 11), date(2026, 7, 16), date(2026, 7, 20)]
        for i, line_date in enumerate(dates):
            self.env["account.bank.statement.line"].create(
                {
                    "journal_id": session.cash_journal_id.id,
                    "pos_session_id": session.id,
                    "payment_ref": f"cash move {i}",
                    "amount": 10.0,
                    "date": line_date,
                }
            )
        before = session.statement_line_ids

        session.sudo()._post_statement_difference(5.0)

        created = session.statement_line_ids - before
        self.assertEqual(len(created), 1, "expected one cash-difference line")
        self.assertEqual(
            created.date,
            max(dates),
            "cash-difference line was dated from the oldest cash movement",
        )
