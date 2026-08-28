from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestPostContract(AccountTestInvoicingCommon):
    def _invoice(self, date, partner=None):
        return self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": (partner or self.partner_a).id,
                "invoice_date": date,
                "date": date,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_a.id,
                            "quantity": 1,
                            "price_unit": 100.0,
                            "tax_ids": [],
                        }
                    )
                ],
            }
        )

    def test_post_returns_a_subset_of_the_moves_it_was_given(self):
        today = fields.Date.context_today(self.env.user)
        same_day = self._invoice(today)
        future = self._invoice(today + timedelta(days=30))

        posted = (same_day | future)._post(soft=True)

        self.assertEqual(posted, same_day)
        self.assertFalse(posted - (same_day | future))
        self.assertEqual(future.state, "draft")
        self.assertEqual(future.auto_post, "at_date")

    def test_hard_post_returns_every_move_and_nothing_else(self):
        today = fields.Date.context_today(self.env.user)
        moves = self._invoice(today) | self._invoice(today, self.partner_b)

        posted = moves._post(soft=False)

        self.assertEqual(posted, moves)

    def test_post_entries_is_the_override_point(self):
        # _post partitions before delegating, so an override placed on _post_entries
        # sees exactly the moves being posted -- the guarantee the whole contract rests
        # on, and the one that silently failed while overrides hung off _post.
        seen = []
        AccountMove = type(self.env["account.move"])
        original = AccountMove._post_entries

        def recording_post_entries(records):
            seen.append(records)
            return original(records)

        today = fields.Date.context_today(self.env.user)
        same_day = self._invoice(today)
        future = self._invoice(today + timedelta(days=30))

        AccountMove._post_entries = recording_post_entries
        try:
            (same_day | future)._post(soft=True)
        finally:
            AccountMove._post_entries = original

        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0], same_day)

    def test_action_post_confirms_only_the_flagged_moves(self):
        today = fields.Date.context_today(self.env.user)
        clean = self._invoice(today)
        flagged = self._invoice(today, self.partner_b)
        self.env.cache.set(
            flagged, flagged._fields["abnormal_amount_warning"], "unusual"
        )
        self.env.cache.set(flagged, flagged._fields["abnormal_date_warning"], False)
        self.env.cache.set(clean, clean._fields["abnormal_amount_warning"], False)
        self.env.cache.set(clean, clean._fields["abnormal_date_warning"], False)

        action = (
            (clean | flagged)
            .with_context(disable_abnormal_invoice_detection=False)
            .action_post()
        )

        self.assertEqual(action["res_model"], "validate.account.move")
        wizard = self.env["validate.account.move"].browse(action["res_id"])
        self.assertEqual(wizard.move_ids, flagged)
        self.assertEqual(clean.state, "posted")
        self.assertEqual(flagged.state, "draft")

    def test_business_rules_run_on_every_document_posting_path(self):
        # action_post is not the only way a person posts a document: the list-view
        # "Confirm Entries" action, the confirmation wizard and the auto-post cron
        # all reach the move without it. Each must apply the same rules.
        calls = []
        AccountMove = type(self.env["account.move"])
        original = AccountMove._post_check_business_rules

        def recording_rules(records):
            calls.append(len(records))
            return original(records)

        today = fields.Date.context_today(self.env.user)
        AccountMove._post_check_business_rules = recording_rules
        try:
            self._invoice(today).action_post()
            self.assertEqual(len(calls), 1, "the Post button skipped the rules")

            self._invoice(today).action_validate_moves_with_confirmation()
            self.assertEqual(len(calls), 2, "the list-view action skipped the rules")

            wizard = self.env["validate.account.move"].create(
                {"move_ids": [Command.set(self._invoice(today).ids)]}
            )
            wizard.validate_move()
            self.assertEqual(len(calls), 3, "the confirmation wizard skipped the rules")

            auto = self._invoice(today)
            auto.auto_post = "at_date"
            # _autopost_draft_entries commits through ir.cron._commit_progress, which
            # a TransactionCase forbids. Neutralise the bookkeeping, not the posting.
            with patch.object(
                type(self.env["ir.cron"]), "_commit_progress", lambda *a, **kw: None
            ):
                self.env["account.move"]._autopost_draft_entries()
            self.assertEqual(len(calls), 4, "the auto-post cron skipped the rules")
        finally:
            AccountMove._post_check_business_rules = original

    def test_business_rules_do_not_run_on_system_generated_postings(self):
        # _post is also the engine for cancellation reversals, POS invoices,
        # cash-basis entries and landed costs. Gating it refused to cancel an
        # invoice for a customer a credit rule had blocked.
        calls = []
        AccountMove = type(self.env["account.move"])
        original = AccountMove._post_check_business_rules

        def recording_rules(records):
            calls.append(len(records))
            return original(records)

        today = fields.Date.context_today(self.env.user)
        invoice = self._invoice(today)
        invoice.action_post()

        AccountMove._post_check_business_rules = recording_rules
        try:
            reversal = invoice._reverse_moves(
                [{"invoice_date": today, "date": today}], cancel=True
            )
            self.assertEqual(reversal.state, "posted")
            self.assertFalse(
                calls, "a cancellation reversal must not be gated by business rules"
            )

            self._invoice(today)._post(soft=False)
            self.assertFalse(calls, "_post itself must not be gated")
        finally:
            AccountMove._post_check_business_rules = original

    def test_non_deductible_names_are_built_after_the_sequence_is_assigned(self):
        today = fields.Date.context_today(self.env.user)
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": today,
                "date": today,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_a.id,
                            "quantity": 1,
                            "price_unit": 100.0,
                            "tax_ids": [Command.set(self.tax_purchase_a.ids)],
                        }
                    )
                ],
            }
        )
        bill.invoice_line_ids[0].deductible_amount = 50.0
        bill.action_post()

        non_deductible = bill.line_ids.filtered(
            lambda line: (
                line.display_type
                in ("non_deductible_product_total", "non_deductible_tax")
            )
        )
        self.assertTrue(non_deductible)
        for line in non_deductible:
            self.assertTrue(line.name.startswith(bill.name))

    def test_payment_bank_account_guard_names_the_payment_it_refuses(self):
        # The guard loops over self but used to read the method line off the whole
        # recordset, so batch-confirming payments from two journals raised
        # "Expected singleton" instead of the message it meant to show.
        AccountPayment = type(self.env["account.payment"])
        original = AccountPayment._get_method_codes_needing_bank_account
        AccountPayment._get_method_codes_needing_bank_account = lambda records: [
            "manual"
        ]
        try:
            journals = self.env["account.journal"].create(
                [
                    {
                        "name": f"Bank {suffix}",
                        "type": "bank",
                        "code": f"BNK{suffix}",
                        "company_id": self.env.company.id,
                    }
                    for suffix in ("X", "Y")
                ]
            )
            payments = self.env["account.payment"].create(
                [
                    {
                        "payment_type": "outbound",
                        "partner_type": "supplier",
                        "partner_id": self.partner_a.id,
                        "amount": 100.0,
                        "journal_id": journal.id,
                        "payment_channel_id": journal.outbound_payment_channel_ids[
                            0
                        ].id,
                    }
                    for journal in journals
                ]
            )
            self.assertEqual(len(payments.payment_channel_id), 2)
            with self.assertRaises(UserError):
                payments.action_post()
        finally:
            AccountPayment._get_method_codes_needing_bank_account = original

    def test_a_move_that_cannot_post_is_not_scheduled(self):
        # A move that reaches auto_post='at_date' while invalid is picked up by the
        # cron on every run, fails, and posts a message each time. Validate before
        # scheduling so it never gets there.
        today = fields.Date.context_today(self.env.user)
        invoice = self._invoice(today + timedelta(days=30))
        invoice.partner_id = False

        with self.assertRaises(UserError):
            invoice._post(soft=True)

        self.assertEqual(invoice.state, "draft")
        self.assertEqual(invoice.auto_post, "no", "an invalid move was scheduled")
