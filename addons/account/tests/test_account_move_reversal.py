from odoo import Command, fields
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountMoveReversal(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.journal = cls.company_data["default_journal_misc"]
        cls.receivable = cls.company_data["default_account_receivable"]
        cls.expense = cls.company_data["default_account_expense"]

    def _post_entry(self):
        move = self.env["account.move"].create(
            {
                "move_type": "entry",
                "journal_id": self.journal.id,
                "date": fields.Date.from_string("2021-01-01"),
                "line_ids": [
                    Command.create(
                        {
                            "account_id": self.receivable.id,
                            "balance": 500.0,
                            "name": "to reverse",
                        }
                    ),
                    Command.create(
                        {
                            "account_id": self.expense.id,
                            "balance": -500.0,
                            "name": "to reverse",
                        }
                    ),
                ],
            }
        )
        move.action_post()
        return move

    def test_reversal_is_named_in_the_original_chatter(self):
        """The reversed entry's chatter must say *which* entry reversed it."""
        move = self._post_entry()

        wizard = self.env["account.move.reversal"].create(
            {
                "move_ids": move.ids,
                "date": fields.Date.from_string("2021-02-01"),
                "journal_id": move.journal_id.id,
            }
        )
        reversed_move = self.env["account.move"].browse(wizard.refund_moves()["res_id"])

        # Only a numbered reversal can be named; a draft one is still "/".
        self.assertEqual(reversed_move.state, "posted")
        self.assertNotEqual(reversed_move.name, "/")
        self.assertTrue(
            any(reversed_move.name in body for body in move.message_ids.mapped("body")),
            "the chatter of a reversed entry must name the entry that reversed it,"
            " otherwise the only way to find it is a filtered search",
        )
