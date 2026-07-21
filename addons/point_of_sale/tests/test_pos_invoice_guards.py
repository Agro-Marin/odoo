# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Regression tests for three defects found in the round-7 point_of_sale audit.
# Each was reproduced against the pre-fix code and fails without the corresponding
# fix:
#   * the receivable aggregation branch swapped `amount_currency` and `balance`,
#     unbalancing the reversal move on any config whose currency is not the
#     company's;
#   * `_generate_pos_order_invoice` had no state guard, so a cancelled or unpaid
#     draft order could be promoted to a posted customer invoice;
#   * `pos.printer` had no multi-company record rule, exposing another company's
#     IoT/printer network addresses to any POS user.
import odoo
from odoo.exceptions import UserError

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@odoo.tests.tagged("post_install", "-at_install")
class TestPosInvoiceGuards(TestPoSCommon):
    def setUp(self):
        super().setUp()
        self.config = self.basic_config
        self.product = self.create_product("Guarded", self.categ_basic, 100.0, 50.0)

    def _make_order(self, state):
        """Create a minimal order and force it into `state`."""
        order = self.env["pos.order"].create(
            {
                "session_id": self.pos_session.id,
                "company_id": self.env.company.id,
                "partner_id": self.customer.id,
                "amount_tax": 0.0,
                "amount_total": 100.0,
                "amount_paid": 0.0,
                "amount_return": 0.0,
                "lines": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.product.id,
                            "qty": 1.0,
                            "price_unit": 100.0,
                            "price_subtotal": 100.0,
                            "price_subtotal_incl": 100.0,
                        },
                    )
                ],
            }
        )
        order.state = state
        return order

    def test_cancelled_order_cannot_be_invoiced(self):
        self._start_pos_session(self.cash_pm1, 0)
        order = self._make_order("cancel")
        with self.assertRaises(UserError):
            order.action_pos_order_invoice()
        self.assertFalse(
            order.account_move,
            "A cancelled order must not produce an invoice: it is excluded from the"
            " session closing entry, so the revenue would never be reversed.",
        )
        self.assertEqual(order.state, "cancel", "state must not be promoted to done")

    def test_unpaid_draft_order_cannot_be_invoiced(self):
        self._start_pos_session(self.cash_pm1, 0)
        order = self._make_order("draft")
        self.assertFalse(order.payment_ids)
        with self.assertRaises(UserError):
            order.action_pos_order_invoice()
        self.assertFalse(
            order.account_move,
            "Invoicing an unpaid order leaves a receivable nothing will ever settle.",
        )

    def test_paid_order_is_still_invoicable(self):
        """Control: the guard must not block the legitimate path."""
        self._start_pos_session(self.cash_pm1, 0)
        order = self._make_order("paid")
        order.action_pos_order_invoice()
        self.assertTrue(order.account_move, "a paid order must remain invoicable")
        self.assertEqual(order.state, "done")

    def test_reversal_move_balances_in_foreign_currency(self):
        """Two non-split payments on one receivable account must aggregate without
        swapping the company- and order-currency figures.

        A cash payment plus its change line is the common real-world trigger, and
        the imbalance is invisible whenever the config currency equals the
        company's -- hence the explicit foreign-currency config here.
        """
        config = self.other_currency_config
        self.config = config
        self._start_pos_session(self.cash_pm2, 0)
        order = self.env["pos.order"].create(
            {
                "session_id": self.pos_session.id,
                "company_id": self.env.company.id,
                "partner_id": self.customer.id,
                "amount_tax": 0.0,
                "amount_total": 100.0,
                "amount_paid": 100.0,
                "amount_return": 20.0,
                "lines": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.product.id,
                            "qty": 1.0,
                            "price_unit": 100.0,
                            "price_subtotal": 100.0,
                            "price_subtotal_incl": 100.0,
                        },
                    )
                ],
            }
        )
        for amount in (120.0, -20.0):
            self.env["pos.payment"].create(
                {
                    "pos_order_id": order.id,
                    "amount": amount,
                    "payment_method_id": self.cash_pm2.id,
                    "payment_date": order.date_order,
                }
            )
        order.state = "paid"

        per_nature = order._prepare_aml_values_list_per_nature()
        payment_terms = per_nature["payment_terms"]
        self.assertEqual(
            len(payment_terms), 1, "the two payments should aggregate onto one line"
        )
        total_balance = sum(
            vals.get("balance", 0.0)
            for vals_list in per_nature.values()
            for vals in vals_list
        )
        self.assertAlmostEqual(
            total_balance,
            0.0,
            places=2,
            msg="reversal move is unbalanced -- amount_currency/balance were swapped"
            " in the aggregation branch",
        )
        converter = self.pos_session._amount_converter
        self.assertAlmostEqual(
            payment_terms[0]["amount_currency"],
            100.0,
            places=2,
            msg="amount_currency must hold the order-currency total",
        )
        self.assertAlmostEqual(
            payment_terms[0]["balance"],
            converter(100.0, order.date_order, False),
            places=2,
            msg="balance must hold the company-currency total",
        )

    def test_printer_is_not_readable_across_companies(self):
        other_company = self.env["res.company"].create({"name": "Audit Other Co"})
        self.env["pos.printer"].create(
            {
                "name": "Foreign printer",
                "printer_type": "epson_epos",
                "epson_printer_ip": "10.9.9.9",
                "company_id": other_company.id,
            }
        )
        pos_user = self.env["res.users"].create(
            {
                "name": "Audit POS user",
                "login": "audit_pos_user_r7",
                "company_id": self.env.company.id,
                "company_ids": [(6, 0, self.env.company.ids)],
                "group_ids": [(4, self.env.ref("point_of_sale.group_pos_user").id)],
            }
        )
        visible = self.env["pos.printer"].with_user(pos_user).search([])
        foreign = visible.sudo().filtered(lambda p: p.company_id != self.env.company)
        self.assertFalse(
            foreign,
            "pos.printer leaks another company's proxy/printer IP addresses to any"
            " POS user when the multi-company record rule is missing",
        )
