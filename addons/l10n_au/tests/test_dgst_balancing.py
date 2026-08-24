from odoo import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestL10nAuDgstBalancing(AccountTestInvoicingCommon):
    """`_get_automatic_balancing_account` is this module's only override of the
    dynamic-line sync, and nothing exercised either of its branches."""

    def _entry(self, account, tax):
        return self.env["account.move"].create(
            {
                "move_type": "entry",
                "date": "2026-01-01",
                "journal_id": self.company_data["default_journal_misc"].id,
                "line_ids": [
                    Command.create(
                        {
                            "name": "line",
                            "account_id": account.id,
                            "balance": 100.0,
                            "tax_ids": [Command.set(tax.ids)],
                        }
                    )
                ],
            }
        )

    def _balancing_line(self, move):
        return move.line_ids.filtered(lambda line: line.display_type == "balancing")

    def test_dgst_entry_balances_into_its_own_account(self):
        dgst = self.env["account.account"].create(
            {
                "name": "DGST",
                "code": "DGST01",
                "account_type": "expense",
                "tag_ids": [Command.set(self.env.ref("l10n_au.account_tag_dgst").ids)],
            }
        )
        move = self._entry(dgst, self.company_data["default_tax_sale"])

        self.assertEqual(
            move._get_automatic_balancing_account(),
            dgst,
            "a single DGST line must balance into the DGST account itself, so only "
            "the tax lines carry a real impact",
        )
        self.assertEqual(self._balancing_line(move).account_id, dgst)

    def test_an_untagged_entry_falls_back_to_the_journal_account(self):
        move = self._entry(
            self.company_data["default_account_expense"],
            self.company_data["default_tax_sale"],
        )

        account = move._get_automatic_balancing_account()
        self.assertEqual(
            account._name,
            "account.account",
            "the override and its super must agree on returning a recordset",
        )
        self.assertNotEqual(account, self.company_data["default_account_expense"])
        self.assertEqual(self._balancing_line(move).account_id, account)
