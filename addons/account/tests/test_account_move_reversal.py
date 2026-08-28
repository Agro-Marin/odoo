from lxml import etree

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

    def test_invoice_and_its_credit_notes_reach_each_other(self):
        """Both ends of a reversal must be one click away on the form."""
        invoice = self.init_invoice("out_invoice", products=self.product_a, post=True)

        wizard = self.env["account.move.reversal"].create(
            {
                "move_ids": invoice.ids,
                "date": invoice.date,
                "journal_id": invoice.journal_id.id,
            }
        )
        credit_note = self.env["account.move"].browse(wizard.refund_moves()["res_id"])

        self.assertEqual(invoice.reversal_move_count, 1)
        self.assertEqual(
            self.env["account.move"].browse(invoice.open_reversal_moves()["res_id"]),
            credit_note,
            "the invoice must offer its credit note",
        )
        self.assertEqual(
            self.env["account.move"].browse(
                credit_note.open_reversed_entry()["res_id"]
            ),
            invoice,
            "the credit note must offer the invoice it reverses",
        )

    def test_reversal_stat_buttons_are_on_the_move_form(self):
        """The actions are unreachable unless the form actually carries them."""
        arch = etree.fromstring(
            self.env["account.move"].get_view(
                self.env.ref("account.view_move_form").id, "form"
            )["arch"]
        )
        for action in ("open_reversal_moves", "open_reversed_entry"):
            self.assertTrue(
                arch.xpath(f"//button[@name='{action}']"),
                f"{action} must be reachable from the move form",
            )
