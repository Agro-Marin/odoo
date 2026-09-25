from unittest.mock import patch

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestMarinPaymentFixes(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bank_journal = cls.company_data["default_journal_bank"]
        cls.cash_journal = cls.company_data["default_journal_cash"]
        cls.other_currency = cls.setup_other_currency("EUR")

    def _payment(self, post=False, **vals):
        payment = self.env["account.payment"].create(
            {
                "amount": 100.0,
                "date": "2026-08-01",
                "partner_id": self.partner_a.id,
                "partner_type": "customer",
                "payment_type": "inbound",
                "journal_id": self.bank_journal.id,
                **vals,
            }
        )
        if post:
            payment.action_post()
        return payment

    def _register(self, moves, **vals):
        return (
            self.env["account.payment.register"]
            .with_context(active_model="account.move", active_ids=moves.ids)
            .create(vals)
        )

    def test_confirming_a_selection_leaves_a_canceled_cash_payment_canceled(self):
        self.cash_journal.inbound_payment_channel_ids.payment_account_id = (
            self.cash_journal.default_account_id
        )
        payment = self._payment(journal_id=self.cash_journal.id)
        self.assertEqual(
            payment.outstanding_account_id.account_type,
            "asset_cash",
            "the premise: a cash payment goes straight to paid on confirm",
        )
        payment.action_cancel()
        other = self._payment(journal_id=self.cash_journal.id)

        (payment + other).action_post()

        self.assertEqual(payment.state, "canceled")
        self.assertFalse(payment.move_id)
        self.assertEqual(other.state, "paid")

    def test_mass_edit_skips_payments_that_carry_no_entry(self):
        with_move = self._payment(post=True)
        self.assertTrue(with_move.move_id)
        with patch.object(
            type(self.env["account.payment"]),
            "_outstanding_account_is_mandatory",
            lambda self: False,
        ):
            self.bank_journal.inbound_payment_channel_ids.payment_account_id = False
            without_move = self._payment()
            self.assertFalse(without_move.outstanding_account_id)
            self.assertFalse(without_move.move_id)

            (with_move + without_move).write({"memo": "edited"})

        self.assertEqual(without_move.memo, "edited")
        self.assertEqual(with_move.memo, "edited")

    def test_register_wizard_warns_about_a_confirmed_payment_of_the_same_amount(self):
        invoice = self.init_invoice(
            "out_invoice", post=True, invoice_date="2026-08-01", amounts=[100.0]
        )
        existing = self._payment(post=True)
        self.assertEqual(existing.state, "in_process")

        wizard = self._register(invoice, payment_date="2026-08-01")

        self.assertEqual(wizard.amount, 100.0)
        self.assertIn(existing, wizard.duplicate_payment_ids)

    def test_register_wizard_compares_payments_in_its_own_currency(self):
        invoice = self.init_invoice(
            "out_invoice",
            post=True,
            invoice_date="2026-08-01",
            amounts=[100.0],
            currency=self.other_currency,
        )
        existing = self._payment(currency_id=self.other_currency.id)
        same_figure_other_currency = self._payment()

        wizard = self._register(invoice, payment_date="2026-08-01")

        self.assertEqual(wizard.currency_id, self.other_currency)
        self.assertIn(existing, wizard.duplicate_payment_ids)
        self.assertNotIn(same_figure_other_currency, wizard.duplicate_payment_ids)

    def test_editing_a_saved_payment_warns_on_the_edited_values(self):
        saved = self._payment()
        twin_of_the_edit = self._payment(amount=200.0)
        self.assertNotIn(twin_of_the_edit, saved.duplicate_payment_ids)

        edited = saved.new({"amount": 200.0}, origin=saved)

        self.assertIn(twin_of_the_edit, edited.duplicate_payment_ids._origin)

    def test_moveless_allocation_books_the_payment_currency(self):
        invoice = self.init_invoice(
            "out_invoice",
            post=True,
            invoice_date="2026-08-01",
            amounts=[100.0],
            currency=self.other_currency,
        )
        payment = self._payment(amount=30.0, invoice_ids=[Command.set(invoice.ids)])
        self.assertFalse(payment.move_id)

        vals_list = payment._get_amls_for_payment_without_move()

        against_invoice = [v for v in vals_list if v.get("reconciled_lines_ids")]
        self.assertTrue(against_invoice)
        for vals in against_invoice:
            self.assertEqual(vals["currency_id"], payment.currency_id.id)
            self.assertAlmostEqual(abs(vals["amount_currency"]), 30.0)

    def test_moveless_leftover_goes_to_the_payment_destination_account(self):
        invoice = self.init_invoice(
            "out_invoice", post=True, invoice_date="2026-08-01", amounts=[100.0]
        )
        other_receivable = self.company_data["default_account_receivable"].copy(
            {"code": "121099"}
        )
        payment = self._payment(
            amount=150.0,
            invoice_ids=[Command.set(invoice.ids)],
            destination_account_id=other_receivable.id,
        )

        vals_list = payment._get_amls_for_payment_without_move()

        leftover = [v for v in vals_list if not v.get("reconciled_lines_ids")]
        self.assertEqual(len(leftover), 1)
        self.assertEqual(leftover[0]["account_id"], other_receivable.id)

    def test_superseding_an_outbound_payment_shrinks_it(self):
        bill = self.init_invoice(
            "in_invoice", post=True, invoice_date="2026-08-01", amounts=[100.0]
        )
        term_line = bill.line_ids.filtered(lambda l: l.display_type == "payment_term")
        payment = self._payment(
            payment_type="outbound",
            partner_type="supplier",
            invoice_ids=[Command.set(bill.ids)],
        )
        self.assertEqual(payment.amount_signed, -100.0)
        self._payment(
            post=True,
            amount=40.0,
            payment_type="outbound",
            partner_type="supplier",
            invoice_ids=[Command.set(bill.ids)],
        )

        payment._supersede_with_payment_move(term_line, -40.0)

        self.assertEqual(payment.amount, 60.0)

    def test_statement_match_of_a_partly_matched_liquidity_line_uses_its_residual(self):
        payment = self._payment(post=True)
        liquidity = payment._seek_for_lines()[0]
        self.assertTrue(liquidity.account_id.reconcile)
        partial = self.env["account.move"].create(
            {
                "move_type": "entry",
                "date": "2026-08-01",
                "line_ids": [
                    Command.create(
                        {
                            "account_id": liquidity.account_id.id,
                            "partner_id": self.partner_a.id,
                            "balance": -40.0,
                        }
                    ),
                    Command.create(
                        {
                            "account_id": self.company_data[
                                "default_account_revenue"
                            ].id,
                            "balance": 40.0,
                        }
                    ),
                ],
            }
        )
        partial.action_post()
        (
            liquidity
            + partial.line_ids.filtered(lambda l: l.account_id == liquidity.account_id)
        ).reconcile()
        self.assertEqual(liquidity.amount_residual, 60.0)
        st_line = self.env["account.bank.statement.line"].create(
            {
                "journal_id": self.bank_journal.id,
                "date": "2026-08-01",
                "payment_ref": "PARTLY",
                "amount": 60.0,
                "partner_id": self.partner_a.id,
            }
        )

        amls, _has_exchange_diff = payment._get_amls_for_reconciliation(st_line)

        self.assertEqual(len(amls), 1)
        self.assertAlmostEqual(amls[0]["balance"], -60.0)
        self.assertAlmostEqual(amls[0]["amount_currency"], -60.0)

    def test_duplicate_bank_accounts_are_found_whatever_the_spacing(self):
        partner_1 = self.env["res.partner"].create({"name": "Spaced"})
        partner_2 = self.env["res.partner"].create({"name": "Packed"})
        spaced = self.env["res.partner.bank.account"].create(
            {
                "acc_number": "BE71 0961 2345 6769",
                "partner_id": partner_1.id,
                "company_id": False,
            }
        )
        self.env["res.partner.bank.account"].create(
            {
                "acc_number": "BE71096123456769",
                "partner_id": partner_2.id,
                "company_id": False,
            }
        )

        self.assertEqual(spaced.duplicate_bank_partner_ids, partner_2)

    def test_a_shared_payment_term_in_use_elsewhere_cannot_be_deleted(self):
        company_b = self.setup_other_company()["company"]
        term = self.env["account.payment.term"].create(
            {
                "name": "Shared term",
                "company_id": False,
                "line_ids": [
                    Command.create(
                        {"value": "percent", "value_amount": 100, "nb_days": 30}
                    )
                ],
            }
        )
        invoice = self.init_invoice(
            "out_invoice",
            invoice_date="2026-08-01",
            amounts=[100.0],
            company=company_b,
        )
        invoice.invoice_payment_term_id = term
        user_a = self.env["res.users"].create(
            {
                "name": "Company A accountant",
                "login": "company_a_accountant",
                "company_id": self.env.company.id,
                "company_ids": [Command.set(self.env.company.ids)],
                "group_ids": [
                    Command.set(self.env.ref("account.group_account_manager").ids)
                ],
            }
        )

        with self.assertRaises(UserError):
            term.with_user(user_a).unlink()
        self.assertTrue(term.exists())

    def test_group_memo_is_not_drawn_while_the_wizard_is_edited(self):
        invoices = self.init_invoice(
            "out_invoice", post=True, invoice_date="2026-08-01", amounts=[100.0]
        ) + self.init_invoice(
            "out_invoice", post=True, invoice_date="2026-08-01", amounts=[50.0]
        )
        Company = type(self.env["res.company"])
        draw = Company.get_next_batch_payment_communication
        drawn = []

        def counting_draw(company):
            drawn.append(company)
            return draw(company)

        with patch.object(
            Company, "get_next_batch_payment_communication", counting_draw
        ):
            wizard = self._register(invoices, group_payment=True)
            wizard.communication
            wizard.amount = 120.0
            wizard.communication
            wizard.amount = 150.0
            wizard.communication
            self.assertEqual(drawn, [])

            payment = wizard._create_payments()

        self.assertEqual(len(drawn), 1)
        self.assertTrue(payment.memo.startswith("GROUP/"))

    def test_group_memo_shows_the_next_number_without_consuming_it(self):
        invoices = self.init_invoice(
            "out_invoice", post=True, invoice_date="2026-08-01", amounts=[100.0]
        ) + self.init_invoice(
            "out_invoice", post=True, invoice_date="2026-08-01", amounts=[50.0]
        )
        wizard = self._register(invoices, group_payment=True)
        preview = wizard.communication
        self.assertTrue(preview.startswith("GROUP/"))
        wizard.amount = 120.0
        self.assertEqual(wizard.communication, preview)

        payment = wizard._create_payments()

        self.assertEqual(payment.memo, preview)

    def test_a_cleared_memo_stays_empty(self):
        single = self.init_invoice(
            "out_invoice", post=True, invoice_date="2026-08-01", amounts=[100.0]
        )
        grouped = self.init_invoice(
            "out_invoice", post=True, invoice_date="2026-08-01", amounts=[40.0]
        ) + self.init_invoice(
            "out_invoice", post=True, invoice_date="2026-08-01", amounts=[60.0]
        )
        for moves, vals in ((single, {}), (grouped, {"group_payment": True})):
            wizard = self._register(moves, **vals)
            self.assertTrue(wizard.communication)
            wizard.communication = False

            payment = wizard._create_payments()

            self.assertFalse(payment.memo)

    def test_an_edited_group_memo_is_kept_and_draws_no_number(self):
        invoices = self.init_invoice(
            "out_invoice", post=True, invoice_date="2026-08-01", amounts=[100.0]
        ) + self.init_invoice(
            "out_invoice", post=True, invoice_date="2026-08-01", amounts=[50.0]
        )
        wizard = self._register(invoices, group_payment=True)
        wizard.communication = "customer reference 42"
        Company = type(self.env["res.company"])
        with patch.object(
            Company,
            "get_next_batch_payment_communication",
            side_effect=AssertionError("drew a GROUP number"),
        ):
            payment = wizard._create_payments()

        self.assertEqual(payment.memo, "customer reference 42")

    def test_duplicate_warning_of_several_edited_payments_at_once(self):
        first, second = self._payment(), self._payment(amount=300.0)
        twin = self._payment(amount=200.0)
        edits = first.new({"amount": 200.0}, origin=first) | second.new(
            {"amount": 200.0}, origin=second
        )

        duplicates = edits.mapped("duplicate_payment_ids")._origin

        self.assertIn(twin, duplicates)

    def test_moveless_refund_leftovers_follow_the_partner_type(self):
        for partner_type, payment_type, account_type in (
            ("customer", "outbound", "asset_receivable"),
            ("supplier", "inbound", "liability_payable"),
        ):
            payment = self._payment(
                amount=40.0, partner_type=partner_type, payment_type=payment_type
            )

            vals_list = payment._get_amls_for_payment_without_move()

            accounts = self.env["account.account"].browse(
                [v["account_id"] for v in vals_list]
            )
            self.assertEqual(set(accounts.mapped("account_type")), {account_type})

    def test_confirming_a_selection_leaves_a_rejected_cash_payment_rejected(self):
        self.cash_journal.inbound_payment_channel_ids.payment_account_id = (
            self.cash_journal.default_account_id
        )
        payment = self._payment(post=True, journal_id=self.cash_journal.id)
        self.assertEqual(payment.state, "paid")
        payment.action_reject()

        (payment + self._payment(journal_id=self.cash_journal.id)).action_post()

        self.assertEqual(payment.state, "rejected")

    def test_unknown_payment_method_code_yields_a_domain(self):
        self.assertTrue(
            self.env["account.payment.method"]._get_domain_payment_method(
                "no_such_method_code"
            )
        )
