from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import SQL

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestMarinHashV5(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.jpy = cls.setup_other_currency(
            "JPY", rounding=1.0, rates=[("1900-01-01", 100.0)]
        )
        cls.company_data["default_journal_sale"].restrict_mode_hash_table = True

    def _post(self, date, amount, currency=None, hash_version=None):
        move = self.init_invoice(
            "out_invoice",
            self.partner_a,
            date,
            amounts=[amount],
            taxes=[],
            currency=currency,
        )
        if hash_version:
            move.with_context(hash_version=hash_version).action_post()
        else:
            move.action_post()
        return move

    def _integrity(self, move):
        results = move.company_id._check_hash_integrity()["results"]
        return next(
            r for r in results if f"({move.sequence_prefix}...)" in r["journal_name"]
        )

    def _assert_intact(self, first_move, last_move):
        result = self._integrity(first_move)
        self.assertEqual(result["msg_cover"], "Entries are correctly hashed")
        self.assertEqual(result["first_move_name"], first_move.name)
        self.assertEqual(result["last_move_name"], last_move.name)

    def _assert_corrupted(self, move):
        self.assertRegex(
            self._integrity(move)["msg_cover"],
            rf"Corrupted data on journal entry with id {move.id} ",
        )

    def _tamper_line(self, line, assignment):
        self.env.flush_all()
        self.env.cr.execute(
            SQL("UPDATE account_move_line SET %s WHERE id = %s", assignment, line.id)
        )
        self.env.invalidate_all()

    def _tamper_debit(self, move, delta):
        self._tamper_line(
            move.line_ids.filtered("debit"),
            SQL("debit = debit + %s, balance = balance + %s", delta, delta),
        )

    def test_cent_tamper_on_zero_decimal_currency_line_breaks_the_hash(self):
        move = self._post("2024-01-01", 50000, currency=self.jpy)
        receivable = move.line_ids.filtered("debit")
        self.assertEqual(receivable.currency_id, self.jpy)
        self.assertEqual(receivable.debit, 500.0)
        self.assertTrue(move.inalterable_hash.startswith("$5$"))
        self._assert_intact(move, move)

        self._tamper_debit(move, 0.01)

        self._assert_corrupted(move)

    def test_amount_currency_tamper_on_v5_move_breaks_the_hash(self):
        move = self._post("2024-01-01", 50000, currency=self.jpy)
        receivable = move.line_ids.filtered("debit")
        self.assertEqual(receivable.amount_currency, 50000)
        self._assert_intact(move, move)

        self._tamper_line(receivable, SQL("amount_currency = amount_currency + 1"))

        self._assert_corrupted(move)

    def test_currency_tamper_on_v5_move_breaks_the_hash(self):
        move = self._post("2024-01-01", 50000, currency=self.jpy)
        receivable = move.line_ids.filtered("debit")

        self._tamper_line(
            receivable, SQL("currency_id = %s", move.company_currency_id.id)
        )

        self._assert_corrupted(move)

    def test_hashed_line_refuses_foreign_amount_and_currency_writes(self):
        move = self._post("2024-01-01", 50000, currency=self.jpy)
        receivable = move.line_ids.filtered("debit")

        receivable.write({"amount_currency": 50000, "currency_id": self.jpy.id})
        with self.assertRaisesRegex(UserError, "Amount in Currency"):
            receivable.write({"amount_currency": 50001})
        with self.assertRaisesRegex(UserError, "Currency"):
            receivable.write({"currency_id": move.company_currency_id.id})
        self._assert_intact(move, move)

    def test_draft_line_in_secured_journal_accepts_foreign_amount_and_currency_writes(
        self,
    ):
        move = self.init_invoice(
            "out_invoice",
            self.partner_a,
            "2024-01-01",
            amounts=[50000],
            taxes=[],
            currency=self.jpy,
        )
        move.write({"currency_id": self.company_data["currency"].id})
        self.assertEqual(move.line_ids.currency_id, self.company_data["currency"])
        move.write({"currency_id": self.jpy.id})
        move.invoice_line_ids.write({"price_unit": 60000})
        self.assertEqual(move.line_ids.filtered("debit").amount_currency, 60000)

        move.action_post()

        self.assertTrue(move.inalterable_hash.startswith("$5$"))
        self._assert_intact(move, move)

    def test_moves_hashed_at_v4_still_verify(self):
        moves = (
            self._post("2024-01-01", 50037, currency=self.jpy, hash_version=4)
            | self._post("2024-01-02", 1234.56, hash_version=4)
            | self._post("2024-01-03", 12345, currency=self.jpy, hash_version=4)
        )
        self.assertEqual(moves[0].line_ids.filtered("debit").debit, 500.37)
        for move in moves:
            self.assertTrue(move.inalterable_hash.startswith("$4$"))
        self.assertEqual(
            moves.line_ids.with_context(hash_version=4)._get_fields_integrity_hash(),
            ["name", "debit", "credit", "account_id", "partner_id"],
        )

        self._assert_intact(moves[0], moves[-1])

    def test_chain_across_v4_to_v5_boundary_verifies(self):
        moves_v4 = self._post(
            "2024-01-01", 50037, currency=self.jpy, hash_version=4
        ) | self._post("2024-01-02", 1000, hash_version=4)
        moves_v5 = self._post("2024-01-03", 12345, currency=self.jpy) | self._post(
            "2024-01-04", 2000
        )
        for move in moves_v4:
            self.assertTrue(move.inalterable_hash.startswith("$4$"))
        for move in moves_v5:
            self.assertTrue(move.inalterable_hash.startswith("$5$"))

        self._assert_intact(moves_v4[0], moves_v5[-1])

        self._tamper_debit(moves_v5[0], 0.01)
        self._assert_corrupted(moves_v5[0])

    def test_v4_prefix_verifies_after_a_v5_move_in_an_earlier_prefix(self):
        move_2024_v4 = self._post("2024-01-01", 1000, hash_version=4)
        move_2025_v4 = self._post("2025-01-01", 1000, hash_version=4)
        move_2024_v5 = self._post("2024-01-02", 1000)
        self.assertNotEqual(move_2024_v4.sequence_prefix, move_2025_v4.sequence_prefix)
        self.assertTrue(move_2024_v5.inalterable_hash.startswith("$5$"))

        self._assert_intact(move_2024_v4, move_2024_v5)
        self._assert_intact(move_2025_v4, move_2025_v4)

    def test_v4_hash_after_a_v5_hash_in_the_same_chain_is_corruption(self):
        move_v5 = self._post("2024-01-01", 1000)
        move_v4 = self._post("2024-01-02", 1000, hash_version=4)
        self.assertTrue(move_v5.inalterable_hash.startswith("$5$"))
        self.assertTrue(move_v4.inalterable_hash.startswith("$4$"))

        self._assert_corrupted(move_v4)

    def test_unknown_hash_version_reports_corruption(self):
        move = self._post("2024-01-01", 1000)
        self.env.flush_all()
        self.env.cr.execute(
            SQL(
                "UPDATE account_move SET inalterable_hash = '$9$' || split_part(inalterable_hash, '$', 3) WHERE id = %s",
                move.id,
            )
        )
        self.env.invalidate_all()

        self._assert_corrupted(move)
