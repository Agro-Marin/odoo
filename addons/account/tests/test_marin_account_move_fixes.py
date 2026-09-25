from datetime import timedelta
from unittest.mock import patch

from lxml import etree

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools.safe_eval import safe_eval

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.account.tests.common_reconcile import TestBankRecWidgetCommon
from odoo.addons.account.tests.test_sequence_mixin import TestSequenceMixinCommon


@tagged("post_install", "-at_install")
class TestAbnormalDateAnchor(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(
            context={**cls.env.context, "disable_abnormal_invoice_detection": False}
        )

    def _bill_vals(self, invoice_date=False, date=None):
        vals = {
            "move_type": "in_invoice",
            "partner_id": self.partner_a.id,
            "invoice_date": invoice_date,
            "line_ids": [
                Command.create(
                    {"name": "product", "price_unit": 100, "tax_ids": [Command.clear()]}
                )
            ],
        }
        if date is not None:
            vals["date"] = date
        return vals

    def _monthly_history(self):
        today = fields.Date.context_today(self.env["account.move"])
        start = today - timedelta(days=30 * 31)
        bills = self.env["account.move"].create(
            [
                self._bill_vals(invoice_date=start + timedelta(days=30 * i))
                for i in range(31)
            ]
        )
        bills.action_post()
        return max(bills.mapped("invoice_date"))

    def test_abnormal_date_flagged_when_invoice_date_is_set(self):
        too_soon = self._monthly_history() + timedelta(days=5)
        bill = self.env["account.move"].create(
            self._bill_vals(invoice_date=too_soon, date=too_soon)
        )
        self.assertTrue(
            bill.abnormal_date_warning,
            "five days into a thirty-day cadence is the anomaly this warns about",
        )

    def test_abnormal_date_flagged_when_only_date_is_set(self):
        too_soon = self._monthly_history() + timedelta(days=5)
        bill = self.env["account.move"].create(
            self._bill_vals(invoice_date=False, date=too_soon)
        )
        self.assertFalse(bill.invoice_date)
        self.assertEqual(bill.date, too_soon)
        self.assertTrue(
            bill.abnormal_date_warning,
            "a bill whose only date is `date` must be judged against `date`, the "
            "anchor its own SQL window used",
        )


@tagged("post_install", "-at_install")
class TestPaymentReferenceFollowsTheNumber(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_sale_journal = cls.company_data["default_journal_sale"].copy(
            {"name": "Second Sale Journal", "code": "SAJ2"}
        )

    def _invoice(self, **extra):
        return self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2026-06-01",
                "journal_id": self.company_data["default_journal_sale"].id,
                "line_ids": [
                    Command.create(
                        {
                            "name": "product",
                            "price_unit": 100,
                            "tax_ids": [Command.clear()],
                        }
                    )
                ],
                **extra,
            }
        )

    def _term_line(self, move):
        return move.line_ids.filtered(lambda line: line.display_type == "payment_term")

    def test_computed_reference_follows_a_journal_change(self):
        invoice = self._invoice()
        invoice.action_post()
        self.assertEqual(invoice.payment_reference, invoice.name)

        invoice.action_draft()
        invoice.write({"name": "/", "journal_id": self.other_sale_journal.id})
        invoice.action_post()

        self.assertEqual(
            invoice.payment_reference,
            invoice.name,
            "the reference was computed from the old number and must be recomputed "
            "from the new one, not left quoting a number that is gone",
        )
        self.assertEqual(
            self._term_line(invoice).name,
            invoice.name,
            "the payment term item labels itself from the move's payment reference",
        )

    def test_computed_reference_survives_an_unchanged_number(self):
        invoice = self._invoice()
        invoice.action_post()
        reference = invoice.payment_reference

        invoice.action_draft()
        invoice.write({"name": "/"})
        invoice.action_post()

        self.assertEqual(invoice.payment_reference, reference)
        self.assertEqual(invoice.payment_reference, invoice.name)

    def test_user_reference_is_never_discarded(self):
        invoice = self._invoice(payment_reference="CUSTOMER-REF-42")
        invoice.action_post()
        self.assertEqual(invoice.payment_reference, "CUSTOMER-REF-42")

        invoice.action_draft()
        invoice.write({"name": "/", "journal_id": self.other_sale_journal.id})
        invoice.action_post()

        self.assertEqual(
            invoice.payment_reference,
            "CUSTOMER-REF-42",
            "renumbering must not touch a reference the compute did not write",
        )


@tagged("post_install", "-at_install")
class TestMarinAccountMoveAuditFixes(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_data_2 = cls.setup_other_company()

    def _entry(self, amount=100.0, account=None, date="2026-01-15", journal=None):
        account = account or self.company_data["default_account_receivable"]
        return self.env["account.move"].create(
            {
                "move_type": "entry",
                "date": date,
                "journal_id": (journal or self.company_data["default_journal_misc"]).id,
                "line_ids": [
                    Command.create(
                        {
                            "name": "debit",
                            "account_id": account.id,
                            "partner_id": self.partner_a.id,
                            "balance": amount,
                        }
                    ),
                    Command.create(
                        {
                            "name": "credit",
                            "account_id": self.company_data[
                                "default_account_revenue"
                            ].id,
                            "balance": -amount,
                        }
                    ),
                ],
            }
        )

    def _bill(self, name, account, invoice_date, partner=None, deductible=None):
        line_vals = {
            "name": name,
            "account_id": account.id,
            "price_unit": 100.0,
            "tax_ids": [Command.set(self.tax_purchase_a.ids)],
        }
        if deductible is not None:
            line_vals["deductible_amount"] = deductible
        return self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": (partner or self.partner_a).id,
                "invoice_date": invoice_date,
                "invoice_line_ids": [Command.create(line_vals)],
            }
        )

    def test_posted_bill_with_non_deductible_lines_can_be_relabelled(self):
        bill = self._bill(
            "Partial item",
            self.company_data["default_account_expense"],
            "2026-01-10",
            deductible=75.0,
        )
        bill.action_post()
        non_deductible = bill.line_ids.filtered(
            lambda line: line.display_type == "non_deductible_product"
        )
        self.assertTrue(non_deductible)

        bill.invoice_line_ids.name = "Relabelled item"

        self.assertEqual(bill.state, "posted")
        self.assertEqual(
            bill.line_ids.filtered(
                lambda line: line.display_type == "non_deductible_product"
            ),
            non_deductible,
            "a posted bill keeps its non-deductible lines when a label changes",
        )

    def test_cash_rounding_accounts_come_from_the_invoice_company(self):
        company_2 = self.company_data_2["company"]
        self.cash_rounding_a.with_company(company_2).write(
            {
                "profit_account_id": self.company_data_2["default_account_revenue"].id,
                "loss_account_id": self.company_data_2["default_account_expense"].id,
            }
        )
        self.assertEqual(self.env.company, self.company_data["company"])

        move = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "company_id": company_2.id,
                "partner_id": self.partner_a.id,
                "invoice_cash_rounding_id": self.cash_rounding_a.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_a.id,
                            "price_unit": 100.42,
                            "tax_ids": [Command.clear()],
                        }
                    )
                ],
            }
        )

        rounding_line = move.line_ids.filtered(
            lambda line: line.display_type == "rounding"
        )
        self.assertEqual(
            rounding_line.account_id,
            self.company_data_2["default_account_revenue"],
        )

    def test_biggest_tax_rounding_without_tax_line_is_kept_across_writes(self):
        self.cash_rounding_a.strategy = "biggest_tax"
        move = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2026-01-10",
                "invoice_cash_rounding_id": self.cash_rounding_a.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "untaxed",
                            "price_unit": 100.42,
                            "tax_ids": [Command.clear()],
                        }
                    )
                ],
            }
        )
        rounding_line = move.line_ids.filtered(
            lambda line: line.display_type == "rounding"
        )
        self.assertTrue(rounding_line)

        move.ref = "touch"
        move.invoice_line_ids.name = "still untaxed"

        self.assertEqual(
            move.line_ids.filtered(lambda line: line.display_type == "rounding"),
            rounding_line,
            "the rounding line of a biggest-tax rounding with no tax line is "
            "updated in place, not recreated on every write",
        )

    def test_signer_is_fixed_when_the_invoice_is_posted(self):
        signer_1 = self.env.user
        signer_2 = self.env.user.copy({"login": "o1e_signer_2"})
        config = self.company_data["company"].account_config_id
        config.signing_user = signer_1
        invoice = self.init_invoice("out_invoice", amounts=[100.0], post=True)
        self.assertEqual(invoice.signing_user, signer_1)

        config.signing_user = signer_2
        self.env.flush_all()
        invoice.invalidate_recordset(["signing_user"])

        self.assertEqual(invoice.signing_user, signer_1)

    def test_quick_edit_suggests_expense_accounts_for_vendor_credit_notes(self):
        expense = self.company_data["default_account_expense"]
        self._bill("service", expense, "2026-01-10").action_post()

        _count, account_id, _taxes = self.env[
            "account.move"
        ]._get_frequent_account_and_taxes(
            self.company_data["company"].id, self.partner_a.id, "in_refund"
        )

        self.assertEqual(account_id, expense.id)

    def test_quick_edit_suggests_the_other_income_account_a_customer_uses(self):
        other_income = self.env["account.account"].create(
            {
                "code": "O1EOTHINC",
                "name": "Other income",
                "account_type": "income_other",
            }
        )
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2026-01-10",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "rent",
                            "account_id": other_income.id,
                            "price_unit": 100.0,
                            "tax_ids": [],
                        }
                    )
                ],
            }
        )
        invoice.action_post()

        _count, account_id, _taxes = self.env[
            "account.move"
        ]._get_frequent_account_and_taxes(
            self.company_data["company"].id, self.partner_a.id, "out_invoice"
        )

        self.assertEqual(account_id, other_income.id)

    def test_sequence_number_of_an_unlinked_last_move_is_reused(self):
        self._entry().action_post()
        self._entry().action_post()
        first = self._entry()
        first.action_post()
        first_name = first.name
        first.action_draft()
        first.unlink()

        second = self._entry()
        second.action_post()

        self.assertEqual(second.name, first_name)

    def test_outstanding_credit_of_a_branch_is_offered_on_the_parent_invoice(self):
        root = self.company_data["company"]
        root.write({"child_ids": [Command.create({"name": "Branch O1E"})]})
        self.cr.precommit.run()
        branch = root.child_ids.filtered(lambda company: company.name == "Branch O1E")

        refund = self.env["account.move"].create(
            {
                "move_type": "out_refund",
                "company_id": branch.id,
                "partner_id": self.partner_a.id,
                "invoice_date": "2026-01-10",
                "invoice_line_ids": [
                    Command.create(
                        {"name": "credit", "price_unit": 50.0, "tax_ids": []}
                    )
                ],
            }
        )
        refund.action_post()
        invoice = self.init_invoice(
            "out_invoice", amounts=[100.0], invoice_date="2026-01-12", post=True
        )

        self.assertIn(
            refund.id,
            [
                content["move_id"]
                for content in (
                    invoice.with_context(
                        allowed_company_ids=(root + branch).ids
                    ).invoice_outstanding_credits_debits_widget
                    or {}
                ).get("content", [])
            ],
        )

        refund_line = refund.line_ids.filtered(
            lambda line: line.account_id.account_type == "asset_receivable"
        )
        invoice.with_context(
            allowed_company_ids=(root + branch).ids
        ).js_add_outstanding_line(refund_line.id)

        self.assertEqual(invoice.amount_residual, 50.0)

    def test_outstanding_credit_of_an_unrelated_company_cannot_be_added(self):
        foreign_refund = self.env["account.move"].create(
            {
                "move_type": "out_refund",
                "company_id": self.company_data_2["company"].id,
                "partner_id": self.partner_a.id,
                "invoice_date": "2026-01-10",
                "invoice_line_ids": [
                    Command.create(
                        {"name": "credit", "price_unit": 50.0, "tax_ids": []}
                    )
                ],
            }
        )
        foreign_refund.action_post()
        invoice = self.init_invoice(
            "out_invoice", amounts=[100.0], invoice_date="2026-01-12", post=True
        )
        foreign_line = foreign_refund.line_ids.filtered(
            lambda line: line.account_id.account_type == "asset_receivable"
        )

        with self.assertRaises(UserError):
            invoice.js_add_outstanding_line(foreign_line.id)

    def test_reversing_several_entries_posts_and_reconciles_each(self):
        entries = self._entry() + self._entry(amount=40.0)
        entries.action_post()

        wizard = self.env["account.move.reversal"].create(
            {
                "move_ids": entries.ids,
                "date": "2026-01-20",
                "journal_id": entries[0].journal_id.id,
            }
        )
        wizard.refund_moves()

        reversals = entries.reversal_move_ids
        self.assertEqual(len(reversals), 2)
        self.assertEqual(set(reversals.mapped("state")), {"posted"})
        receivable_lines = entries.line_ids.filtered(
            lambda line: (
                line.account_id == self.company_data["default_account_receivable"]
            )
        )
        self.assertTrue(all(receivable_lines.mapped("reconciled")))

    def test_invoice_reader_without_accounting_rights_reads_cash_rounded_totals(self):
        readers = self.env["res.groups"].create({"name": "o1e invoice readers"})
        self.env["ir.access"].create(
            [
                {
                    "name": f"o1e read {model}",
                    "model_id": self.env["ir.model"]._get_id(model),
                    "group_id": readers.id,
                    "kind": "permission",
                    "operation": "r",
                }
                for model in ("account.move", "account.move.line")
            ]
        )
        reader = self.env["res.users"].create(
            {
                "name": "o1e reader",
                "login": "o1e_reader",
                "company_id": self.env.company.id,
                "company_ids": [Command.set(self.env.company.ids)],
                "group_ids": [
                    Command.set((self.env.ref("base.group_user") + readers).ids)
                ],
            }
        )
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2026-01-10",
                "invoice_cash_rounding_id": self.cash_rounding_a.id,
                "invoice_line_ids": [
                    Command.create({"name": "item", "price_unit": 100.0, "tax_ids": []})
                ],
            }
        )
        invoice.action_post()
        self.env.invalidate_all()

        totals = invoice.with_user(reader).tax_totals

        self.assertTrue(totals)

    def test_prediction_learns_from_the_most_recent_bills(self):
        partner = self.env["res.partner"].create({"name": "o1e predicted vendor"})
        old_account, new_account = self.env["account.account"].create(
            [
                {"code": "O1EOLD", "name": "Old", "account_type": "expense"},
                {"code": "O1ENEW", "name": "New", "account_type": "expense"},
            ]
        )
        self._bill("Consulting fees", old_account, "2020-01-10", partner).action_post()
        self._bill("Consulting fees", new_account, "2026-01-10", partner).action_post()
        self.env["ir.config_parameter"].sudo().set_param(
            "account.bill.predict.history.limit", "1"
        )
        draft = self.env["account.move"].create(
            {"move_type": "in_invoice", "partner_id": partner.id}
        )

        predicted = self.env["account.move.line"]._predict_specific_account(
            draft, "Consulting fees", partner
        )

        self.assertEqual(predicted, new_account.id)

    def test_preferred_payment_channel_follows_the_money_direction(self):
        self.partner_a.write(
            {
                "property_inbound_payment_channel_id": self.inbound_payment_channel.id,
                "property_outbound_payment_channel_id": self.outbound_payment_channel.id,
            }
        )
        expected = {
            "out_invoice": self.inbound_payment_channel,
            "out_receipt": self.inbound_payment_channel,
            "in_refund": self.inbound_payment_channel,
            "in_invoice": self.outbound_payment_channel,
            "out_refund": self.outbound_payment_channel,
        }
        for move_type, channel in expected.items():
            move = self.env["account.move"].new(
                {"move_type": move_type, "partner_id": self.partner_a.id}
            )
            self.assertEqual(move.preferred_payment_channel_id, channel, move_type)

    def test_the_visible_payment_channel_field_admits_the_computed_channel(self):
        self.partner_a.write(
            {
                "property_inbound_payment_channel_id": self.inbound_payment_channel.id,
                "property_outbound_payment_channel_id": self.outbound_payment_channel.id,
            }
        )
        arch = etree.fromstring(
            self.env["account.move"].get_view(
                self.env.ref("account.view_move_form").id, "form"
            )["arch"]
        )
        nodes = arch.xpath("//field[@name='preferred_payment_channel_id']")
        self.assertEqual(len(nodes), 2)
        for move_type in ("out_invoice", "out_refund", "in_invoice", "in_refund"):
            move = self.env["account.move"].new(
                {"move_type": move_type, "partner_id": self.partner_a.id}
            )
            visible = [
                node
                for node in nodes
                if not safe_eval(node.get("invisible"), {"move_type": move_type})
            ]
            self.assertEqual(len(visible), 1, move_type)
            self.assertIn(
                f"'payment_type', '=', '{move.preferred_payment_channel_id.payment_type}'",
                visible[0].get("domain"),
                move_type,
            )

    def test_batch_send_summary_uses_the_translated_sending_method_label(self):
        self.partner_a.write(
            {"email": "partner_a@example.com", "invoice_sending_method": "email"}
        )
        invoice = self.init_invoice("out_invoice", amounts=[100.0], post=True)
        Selection = type(self.env["res.partner"]._fields["invoice_sending_method"])
        describe = Selection._description_selection

        def translated(field, env):
            if field.name == "invoice_sending_method":
                return [("manual", "Manual"), ("email", "por correo")]
            return describe(field, env)

        with patch.object(Selection, "_description_selection", translated):
            wizard = self.env["account.move.send.batch.wizard"].create(
                {"move_ids": [Command.set(invoice.ids)]}
            )
            summary = wizard.summary_data

        self.assertEqual(summary["email"]["label"], "por correo")

    def test_adjusting_entry_origin_action_is_named_after_its_single_origin(self):
        invoice = self.init_invoice("out_invoice", amounts=[100.0], post=True)
        adjusting = self._entry()
        adjusting.adjusting_entry_origin_move_ids = invoice

        action = adjusting.open_adjusting_entry_origin_moves()

        self.assertEqual(action["name"], adjusting.adjusting_entry_origin_label)
        self.assertEqual(action["name"], "Customer Invoice")


@tagged("post_install", "-at_install")
class TestMarinDeferralLinks(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        config = cls.company.account_config_id
        config.deferred_expense_journal_id = cls.company_data["default_journal_misc"]
        config.deferred_revenue_journal_id = cls.company_data["default_journal_misc"]
        config.deferred_expense_account_id = cls.company_data[
            "default_account_deferred_expense"
        ]
        config.deferred_revenue_account_id = cls.company_data[
            "default_account_deferred_revenue"
        ]
        cls.revenue_account = cls.env["account.account"].create(
            {"name": "O1E Revenue", "code": "O1EREV", "account_type": "income"}
        )

    def _deferred_invoice(self, amount=1680.0, date="2023-03-15", currency=None):
        vals = {
            "move_type": "out_invoice",
            "partner_id": self.partner_a.id,
            "date": date,
            "invoice_date": date,
            "invoice_line_ids": [
                Command.create(
                    {
                        "name": "deferred",
                        "account_id": self.revenue_account.id,
                        "price_unit": amount,
                        "tax_ids": [Command.clear()],
                        "deferred_start_date": "2023-01-01",
                        "deferred_end_date": "2023-03-31",
                    }
                )
            ],
        }
        if currency:
            vals["currency_id"] = currency.id
        move = self.env["account.move"].create(vals)
        move.action_post()
        return move

    def test_resetting_several_invoices_keeps_each_deferral_with_its_own_invoice(self):
        invoice_a = self._deferred_invoice()
        invoice_b = self._deferred_invoice(amount=900.0)
        self.company.account_config_id.fiscalyear_lock_date = "2023-02-15"

        (invoice_a + invoice_b).action_draft()

        for invoice in invoice_a + invoice_b:
            self.assertTrue(invoice.deferred_move_ids)
            self.assertEqual(
                invoice.deferred_move_ids.deferred_original_move_ids,
                invoice,
                "a reversal is linked only to the invoice whose deferral it reverses",
            )

    def test_deleting_one_deferral_keeps_the_others_linked(self):
        invoice = self._deferred_invoice()
        deferrals = invoice.deferred_move_ids
        self.assertGreater(len(deferrals), 1)
        self.company.account_config_id.restrictive_audit_trail = True
        deleted = deferrals.filtered(lambda move: move.state == "posted")[-1:]

        deleted.unlink()

        self.assertEqual(invoice.deferred_move_ids, deferrals - deleted)

    def test_deferral_of_a_coarse_currency_invoice_leaves_nothing_behind(self):
        coarse = self.setup_other_currency(
            "JPY", rounding=1.0, rates=[("1900-01-01", 1.0)]
        )
        invoice = self._deferred_invoice(amount=100.0, currency=coarse)

        deferred_account = self.company_data["default_account_deferred_revenue"]
        self.assertAlmostEqual(
            sum(
                invoice.deferred_move_ids.line_ids.filtered(
                    lambda line: line.account_id == deferred_account
                ).mapped("balance")
            ),
            0.0,
            places=2,
        )


@tagged("post_install", "-at_install")
class TestMarinStatementPartialRemoval(TestBankRecWidgetCommon):
    def test_removing_one_statement_payment_keeps_the_other(self):
        st_line_1 = self._create_st_line(50.0, partner_id=self.partner_a.id)
        st_line_2 = self._create_st_line(50.0, partner_id=self.partner_a.id)
        invoice = self.init_invoice(
            "out_invoice",
            invoice_date="2019-01-01",
            amounts=[100.0],
            partner=self.partner_a,
            post=True,
        )
        for st_line in st_line_1 + st_line_2:
            invoice.js_add_outstanding_line(
                st_line.move_id.line_ids.filtered(
                    lambda line: line.account_id.account_type == "asset_cash"
                ).id
            )
        partial = invoice.line_ids.matched_credit_ids.filtered(
            lambda partial: partial.credit_move_id.move_id == st_line_1.move_id
        )
        self.assertTrue(partial)

        st_line_1.move_id.js_remove_outstanding_partial(partial.id)

        self.assert_invoice_outstanding_reconciled_widget(
            invoice, {st_line_2.move_id.id: 50.0}
        )

    def test_removing_a_partial_of_another_document_is_refused(self):
        st_line = self._create_st_line(50.0, partner_id=self.partner_a.id)
        other = self._create_st_line(50.0, partner_id=self.partner_a.id)
        invoice = self.init_invoice(
            "out_invoice",
            invoice_date="2019-01-01",
            amounts=[100.0],
            partner=self.partner_a,
            post=True,
        )
        invoice.js_add_outstanding_line(
            st_line.move_id.line_ids.filtered(
                lambda line: line.account_id.account_type == "asset_cash"
            ).id
        )
        partial = invoice.line_ids.matched_credit_ids

        with self.assertRaises(UserError):
            other.move_id.js_remove_outstanding_partial(partial.id)

    def test_credit_warning_excludes_a_foreign_statement_payment_once(self):
        foreign = self.setup_other_currency("EUR", rates=[("1900-01-01", 2.0)])
        foreign_journal = self.company_data["default_journal_bank"].copy(
            {"currency_id": foreign.id}
        )
        invoice = self._create_invoice_line(
            "out_invoice",
            currency_id=foreign.id,
            invoice_line_ids=[{"price_unit": 2000.0, "tax_ids": []}],
        ).move_id
        st_line = self._create_st_line(
            600.0,
            date="2017-01-01",
            partner_id=self.partner_a.id,
            journal_id=foreign_journal.id,
        )
        invoice.js_add_outstanding_line(
            st_line.move_id.line_ids.filtered(
                lambda line: line.account_id.account_type == "asset_cash"
            ).id
        )
        invoice.action_draft()
        partials = invoice.line_ids.matched_credit_ids
        self.assertEqual(partials.credit_currency_id, foreign)
        self.assertAlmostEqual(sum(partials.mapped("amount")), 300.0)

        self.assertAlmostEqual(
            invoice._get_partner_credit_warning_exclude_amount(), 300.0
        )


@tagged("post_install", "-at_install")
class TestMarinSequenceGapSuffix(TestSequenceMixinCommon):
    def _sequence_moves(self, suffix, count=3):
        moves = self.env["account.move"]
        for number in range(1, 1 + count):
            moves += self.create_move(name=f"NEW/00000{number}{suffix}", post=True)
        return moves

    def test_a_gap_in_one_suffix_does_not_flag_another(self):
        plain = self._sequence_moves("")
        suffixed = self._sequence_moves("A")

        middle = suffixed[1]
        middle.action_draft()
        middle.name = "NEW/000004A"
        middle.action_post()

        self.assertEqual(
            suffixed.sorted("sequence_number").mapped("made_sequence_gap"),
            [False, True, False],
        )
        self.assertEqual(plain.mapped("made_sequence_gap"), [False, False, False])

    def test_other_suffixes_do_not_fill_the_neighbour_window(self):
        self._sequence_moves("SPACER", count=9)
        first = self.create_move(name="NEW/000001A", post=True)
        ninth = self.create_move(name="NEW/000009A", post=True)

        self.assertFalse(first.made_sequence_gap)
        self.assertTrue(ninth.made_sequence_gap)

    def test_like_wildcards_in_a_suffix_are_literal(self):
        plain = self._sequence_moves("A")
        wild = self._sequence_moves("_A")
        middle = wild[1]
        middle.action_draft()
        middle.name = "NEW/000004_A"
        middle.action_post()

        self.assertEqual(
            wild.sorted("sequence_number").mapped("made_sequence_gap"),
            [False, True, False],
        )
        self.assertEqual(plain.mapped("made_sequence_gap"), [False, False, False])
