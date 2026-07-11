"""Regression tests for marin-fork correctness fixes on account.move.

Each test below fails on the pre-fix code and passes after it:

* ``@api.depends`` completeness so cached compute values are not stale
  (``partner_credit_warning``, ``has_reconciled_entries``, ``tax_totals``,
  ``display_inactive_currency_warning``, ``payment_term_details``);
* ``_sanitize_vals`` / ``_reverse_moves`` no longer mutate caller-owned
  dicts/lists;
* the partial-deductibility group reveal extracted out of ``_post``.
"""

from odoo import Command, fields
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountMoveMarinDepends(AccountTestInvoicingCommon):
    # ----- @api.depends completeness (registry-level) -------------------
    def _deps(self, fname):
        field = self.env["account.move"]._fields[fname]
        return tuple(self.env.registry.field_depends.get(field, ()))

    def test_depends_completeness(self):
        self.assertIn("state", self._deps("partner_credit_warning"))
        self.assertIn("move_type", self._deps("partner_credit_warning"))
        self.assertIn("state", self._deps("display_inactive_currency_warning"))
        self.assertIn("invoice_cash_rounding_id", self._deps("tax_totals"))
        recon = self._deps("has_reconciled_entries")
        self.assertIn("line_ids.matched_debit_ids", recon)
        self.assertIn("line_ids.matched_credit_ids", recon)
        self.assertIn("line_ids.amount_currency", self._deps("payment_term_details"))

    # ----- functional: stale cached warnings ----------------------------
    def test_partner_credit_warning_clears_on_post(self):
        self.env.company.account_use_credit_limit = True
        self.partner_a.credit_limit = 1.0
        invoice = self.init_invoice(
            "out_invoice", partner=self.partner_a, amounts=[1000.0], post=False
        )
        self.assertTrue(invoice.partner_credit_warning, "over-limit draft must warn")
        invoice.action_post()
        self.assertFalse(
            invoice.partner_credit_warning,
            "warning must clear once posted (state is a dependency)",
        )

    def test_has_reconciled_entries_updates_on_reconcile(self):
        invoice = self.init_invoice(
            "out_invoice", partner=self.partner_a, amounts=[100.0], post=True
        )
        self.assertFalse(invoice.has_reconciled_entries)
        self.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=invoice.ids
        ).create({})._create_payments()
        self.assertTrue(
            invoice.has_reconciled_entries,
            "field must flip once the invoice is reconciled with its payment",
        )

    # ----- non-mutation of caller-owned data ----------------------------
    def test_sanitize_vals_does_not_mutate_caller(self):
        vals = {
            "move_type": "out_invoice",
            "invoice_line_ids": [
                Command.create({"name": "A", "quantity": 1, "price_unit": 10})
            ],
            "line_ids": [
                Command.create({"name": "B", "quantity": 1, "price_unit": 20})
            ],
        }
        original_line_ids = vals["line_ids"]
        result = self.env["account.move"]._sanitize_vals(vals)
        self.assertIn("invoice_line_ids", vals, "caller dict must be untouched")
        self.assertEqual(len(vals["line_ids"]), 1, "caller list must not grow")
        self.assertIs(vals["line_ids"], original_line_ids)
        self.assertNotIn("invoice_line_ids", result)
        self.assertEqual(len(result["line_ids"]), 2)

    def test_reverse_moves_does_not_mutate_default_values(self):
        invoice = self.init_invoice(
            "out_invoice", partner=self.partner_a, amounts=[100.0], post=True
        )
        default_values = {"ref": "keep-me"}
        invoice._reverse_moves([default_values])
        self.assertEqual(
            default_values,
            {"ref": "keep-me"},
            "caller's default_values dict must not be mutated in place",
        )

    # ----- extracted partial-deductibility group reveal -----------------
    def test_partial_deductibility_group_reveal_extracted(self):
        move_model = self.env["account.move"]
        self.assertTrue(
            hasattr(move_model, "_reveal_partial_deductibility_group"),
            "group reveal must be an explicit, overridable hook",
        )
        user = self.env["res.users"].create(
            {
                "name": "Poster",
                "login": "marin_poster_test",
                "company_id": self.env.company.id,
                "company_ids": [Command.set(self.env.company.ids)],
                "group_ids": [
                    Command.link(self.env.ref("account.group_account_invoice").id)
                ],
            }
        )
        group_xmlid = "account.group_partial_purchase_deductibility"
        self.assertFalse(user.has_group(group_xmlid))
        bill = move_model.with_user(user).create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": fields.Date.today(),
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "partial",
                            "quantity": 1,
                            "price_unit": 100,
                            "tax_ids": [],
                            "deductible_amount": 50,
                        }
                    )
                ],
            }
        )
        bill.with_user(user).action_post()
        user.invalidate_recordset(["group_ids"])
        self.assertTrue(
            user.has_group(group_xmlid),
            "posting a partially-deductible bill still reveals the feature",
        )
