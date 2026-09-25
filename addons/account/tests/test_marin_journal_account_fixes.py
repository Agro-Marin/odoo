from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from freezegun import freeze_time
from werkzeug.exceptions import NotFound
from werkzeug.wrappers import Response

from odoo import Command
from odoo.tests import tagged

from odoo.addons.account.controllers.download_docs import (
    AccountDocumentDownloadController,
)
from odoo.addons.account.controllers.main import AccountReportController
from odoo.addons.account.controllers.portal import PortalAccount
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestMarinJournalAccountFixes(AccountTestInvoicingCommon):
    def _post_move(self, move_type, account, partner=None, amount=100.0):
        move = self.env["account.move"].create(
            {
                "move_type": move_type,
                "partner_id": (partner or self.partner_a).id,
                "invoice_date": "2026-08-01",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "line",
                            "account_id": account.id,
                            "price_unit": amount,
                            "tax_ids": [Command.clear()],
                        }
                    )
                ],
            }
        )
        move.action_post()
        return move

    def test_the_unaffected_earnings_account_is_created_without_warning(self):
        company = self.env["res.company"].create({"name": "unaffected probe"})
        self.env.user.company_ids |= company
        with self.assertNoLogs("odoo.models", "WARNING"):
            account = company.with_context(
                install_module="l10n_be"
            ).get_unaffected_earnings_account()

        self.assertEqual(
            account, self.env.ref(f"account.{company.id}_unaffected_earnings_account")
        )

    def test_group_display_name_equality_search_matches_on_the_code_prefix(self):
        group = self.env["account.group"].create(
            {"name": "Marin probe", "code_prefix_start": "987654"}
        )

        found = self.env["account.group"].search(
            [("display_name", "=", "987654 Marin probe")]
        )

        self.assertEqual(found, group)

    def test_group_parent_is_the_longest_enclosing_prefix(self):
        groups = self.env["account.group"].create(
            [
                {"name": "one", "code_prefix_start": "97"},
                {"name": "range", "code_prefix_start": "970", "code_prefix_end": "979"},
                {"name": "leaf", "code_prefix_start": "9712"},
            ]
        )

        self.assertEqual(groups[2].parent_id, groups[1])
        self.assertEqual(groups[1].parent_id, groups[0])
        self.assertFalse(groups[0].parent_id)

    def test_credit_note_suggestions_follow_the_document_side_not_the_money(self):
        partner = self.env["res.partner"].create({"name": "frequency probe"})
        revenue = self.company_data["default_account_revenue"]
        expense = self.company_data["default_account_expense"]
        self._post_move("out_invoice", revenue, partner)
        self._post_move("in_invoice", expense, partner)
        self._post_move("in_invoice", expense, partner)
        Account = self.env["account.account"]

        out_refund = Account._get_most_frequent_accounts_for_partner(
            self.env.company.id, partner.id, "out_refund"
        )
        in_refund = Account._get_most_frequent_accounts_for_partner(
            self.env.company.id, partner.id, "in_refund"
        )

        self.assertEqual(out_refund, [revenue.id])
        self.assertEqual(in_refund, [expense.id])
        self.assertTrue(
            Account._get_most_frequent_account_for_partner(
                self.env.company.id, partner.id, None
            )
        )

    def test_suggestions_keep_the_other_income_and_other_expense_accounts(self):
        partner = self.env["res.partner"].create({"name": "other side probe"})
        other_income, other_expense = self.env["account.account"].create(
            [
                {
                    "name": "Other income",
                    "code": "OINC9",
                    "account_type": "income_other",
                },
                {
                    "name": "Other expense",
                    "code": "OEXP8",
                    "account_type": "expense_other",
                },
            ]
        )
        self._post_move("out_invoice", other_income, partner)
        self._post_move("in_invoice", other_expense, partner)
        Account = self.env["account.account"]

        self.assertIn(
            other_income.id,
            Account._get_most_frequent_accounts_for_partner(
                self.env.company.id, partner.id, "out_invoice"
            ),
        )
        self.assertIn(
            other_expense.id,
            Account._get_most_frequent_accounts_for_partner(
                self.env.company.id, partner.id, "in_refund"
            ),
        )

    def test_suggestions_count_documents_of_the_same_side_only(self):
        partner = self.env["res.partner"].create({"name": "clearing probe"})
        billed = self.company_data["default_account_expense"]
        clearing = billed.copy({"code": "610999", "name": "Clearing expense"})
        self._post_move("in_invoice", billed, partner)
        for _ in range(3):
            entry = self.env["account.move"].create(
                {
                    "move_type": "entry",
                    "line_ids": [
                        Command.create(
                            {
                                "account_id": clearing.id,
                                "partner_id": partner.id,
                                "balance": 10.0,
                            }
                        ),
                        Command.create(
                            {
                                "account_id": self.company_data[
                                    "default_account_revenue"
                                ].id,
                                "balance": -10.0,
                            }
                        ),
                    ],
                }
            )
            entry.action_post()

        suggested = self.env["account.account"]._get_most_frequent_accounts_for_partner(
            self.env.company.id, partner.id, "in_invoice"
        )

        self.assertEqual(suggested, [billed.id])

    def test_plain_display_name_does_not_query_account_frequencies(self):
        account = self.company_data["default_account_revenue"]
        Account = type(self.env["account.account"])
        with patch.object(
            Account,
            "_get_most_frequent_accounts_for_partner",
            side_effect=AssertionError("frequency query ran"),
        ):
            name = account.with_context(
                move_type="out_invoice", partner_id=self.partner_a.id
            ).display_name

        self.assertTrue(name)

    def test_opening_date_written_on_several_configs_syncs_returns_once(self):
        other = self.setup_other_company(name="returns sync probe")["company"]
        configs = (self.env.company | other).account_config_id
        seen = []
        ReturnType = type(self.env["account.return.type"])

        def record_sync(return_types, roots):
            seen.append((roots, return_types.env.context.get("forced_date_from")))

        with patch.object(ReturnType, "_sync_all_returns", record_sync):
            configs.write({"account_opening_date": date(2026, 1, 1)})
            configs.write({"account_opening_date": False})

        self.assertEqual(
            seen,
            [
                (
                    (self.env.company | other).root_id,
                    date(2026, 1, 1) - relativedelta(years=2),
                )
            ],
        )

    def test_dashboard_closed_period_of_a_branch_follows_its_parent_lock(self):
        branch = self.env["res.company"].create(
            {"name": "dashboard lock branch", "parent_id": self.env.company.id}
        )
        self.env.user.company_ids |= branch
        branch_journal = self.env["account.journal"].create(
            {
                "name": "Branch bank",
                "code": "BRBNK",
                "type": "bank",
                "company_id": branch.id,
            }
        )
        self.env.company.account_config_id.hard_lock_date = date(2025, 12, 31)

        self.assertEqual(branch_journal._get_closed_period_end(), date(2025, 12, 31))

    def test_any_account_types_cover_the_whole_account_type_selection(self):
        from odoo.addons.account.models.account_journal import ANY_ACCOUNT_TYPES

        selection = (
            self.env["account.account"]._fields["account_type"].get_values(self.env)
        )

        self.assertEqual(set(ANY_ACCOUNT_TYPES), set(selection))

    def test_dashboard_counts_misc_operations_after_a_hard_lock_alone(self):
        journal = self.company_data["default_journal_bank"]
        journal.company_id.account_config_id.hard_lock_date = date(2026, 3, 31)

        limits = journal._get_misc_operations_date_limits()

        self.assertEqual(limits[journal.id], date(2026, 3, 31))

    def test_post_all_entries_leaves_posted_moves_out_of_the_selection(self):
        journal = self.company_data["default_journal_misc"]
        posted, draft = self.env["account.move"].create(
            [
                {
                    "journal_id": journal.id,
                    "line_ids": [
                        Command.create(
                            {
                                "account_id": self.company_data[
                                    "default_account_revenue"
                                ].id,
                                "balance": 10.0,
                            }
                        ),
                        Command.create(
                            {
                                "account_id": self.company_data[
                                    "default_account_expense"
                                ].id,
                                "balance": -10.0,
                            }
                        ),
                    ],
                }
            ]
            * 2
        )
        posted.action_post()
        Move = type(self.env["account.move"])
        with patch.object(
            Move, "action_post_moves_with_confirmation", autospec=True
        ) as confirm:
            journal.action_post_all_entries()

        self.assertEqual(confirm.call_args.args[0], draft)

    @freeze_time("2026-09-25 03:00:00")
    def test_portal_overdue_invoices_use_the_user_s_today(self):
        contact = self.env["res.partner"].create({"name": "portal contact"})
        portal_user = self.env["res.users"].create(
            {
                "name": "portal contact",
                "login": "marin_portal_overdue",
                "partner_id": contact.id,
                "tz": "America/Mexico_City",
                "group_ids": [Command.set([self.env.ref("base.group_portal").id])],
            }
        )
        due_yesterday_in_utc, due_last_week = self.env["account.move"].create(
            [
                {
                    "move_type": "out_invoice",
                    "partner_id": contact.id,
                    "invoice_date": "2026-09-01",
                    "invoice_date_due": due,
                    "invoice_line_ids": [
                        Command.create({"name": "line", "price_unit": 100.0})
                    ],
                }
                for due in ("2026-09-24", "2026-09-17")
            ]
        )
        (due_yesterday_in_utc | due_last_week).action_post()
        sibling = self.env["res.partner"].create({"name": "someone else"})
        foreign = due_last_week.copy({"partner_id": sibling.id})
        foreign.action_post()
        fake_request = SimpleNamespace(env=self.env(user=portal_user))
        with patch("odoo.addons.account.controllers.portal.request", fake_request):
            domain = PortalAccount()._get_domain_overdue_invoices()

        overdue = self.env["account.move"].search(domain)
        self.assertIn(due_last_week, overdue)
        self.assertNotIn(due_yesterday_in_utc, overdue)
        self.assertNotIn(foreign, overdue)

    def test_attachment_download_rejects_non_partner_attachments_with_not_found(self):
        attachment = self.env["ir.attachment"].create(
            {
                "name": "probe.txt",
                "raw": b"probe",
                "res_model": "account.account",
                "res_id": self.company_data["default_account_revenue"].id,
            }
        )

        with self.assertRaises(NotFound):
            AccountReportController().download_report_attachments(attachment)

    def test_attachments_zip_is_served_as_application_zip(self):
        partner = self.partner_a
        attachments = self.env["ir.attachment"].create(
            [
                {
                    "name": name,
                    "raw": b"probe",
                    "res_model": "res.partner",
                    "res_id": partner.id,
                }
                for name in ("a.txt", "b.txt")
            ]
        )
        fake_request = SimpleNamespace(
            prepare_response=lambda content, headers: Response(content, headers=headers)
        )
        with patch("odoo.addons.account.controllers.main.request", fake_request):
            response = AccountReportController().download_report_attachments(
                attachments
            )

        self.assertEqual(response.headers["Content-Type"], "application/zip")

    def test_document_download_reads_allow_fallback_from_the_query_string(self):
        invoice = self.init_invoice("out_invoice", post=True, amounts=[10.0])
        Move = type(self.env["account.move"])
        received = []

        def record_fallback(move, filetype, allow_fallback=False):
            received.append(allow_fallback)
            return {
                "filename": "x.pdf",
                "filetype": "application/pdf",
                "content": b"x",
            }

        fake_request = SimpleNamespace(
            prepare_response=lambda content, headers: Response(
                content, headers=headers
            ),
            env=self.env,
        )
        with (
            patch.object(Move, "_get_invoice_legal_documents", record_fallback),
            patch(
                "odoo.addons.account.controllers.download_docs.request", fake_request
            ),
        ):
            controller = AccountDocumentDownloadController()
            controller.download_invoice_documents_filetype(
                invoice, "pdf", allow_fallback="false"
            )
            controller.download_invoice_documents_filetype(
                invoice, "pdf", allow_fallback="true"
            )

        self.assertEqual(received, [False, True])

    def test_analytic_invoice_button_lists_what_it_counts(self):
        plan = self.env["account.analytic.plan"].create({"name": "count probe"})
        analytic = self.env["account.analytic.account"].create(
            {"name": "count probe", "plan_id": plan.id}
        )
        receipt = self.env["account.move"].create(
            {
                "move_type": "out_receipt",
                "partner_id": self.partner_a.id,
                "invoice_date": "2026-08-01",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "receipt",
                            "price_unit": 50.0,
                            "analytic_distribution": {analytic.id: 100},
                        }
                    )
                ],
            }
        )
        receipt.action_post()

        draft = receipt.copy({"move_type": "out_invoice"})
        self.assertEqual(draft.state, "draft")

        self.assertEqual(analytic.invoice_count, 1)
        action = analytic.action_view_invoice()
        self.assertEqual(
            self.env["account.move"].search(action["domain"]), receipt | draft
        )

    def test_tax_merge_sees_hashed_entries_that_only_use_the_tax_as_base(self):
        exempt = self.env["account.tax"].create(
            {"name": "marin exempt probe", "amount": 0.0}
        )
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2026-08-01",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "exempt",
                            "price_unit": 100.0,
                            "tax_ids": [Command.set(exempt.ids)],
                        }
                    )
                ],
            }
        )
        invoice.action_post()
        self.assertFalse(invoice.line_ids.filtered("tax_line_id"))
        self.env.cr.execute(
            "UPDATE account_move SET inalterable_hash = 'probe' WHERE id = %s",
            [invoice.id],
        )
        invoice.invalidate_recordset(["inalterable_hash"])

        line = self.env["account.tax.merge.wizard.line"].new({"tax_id": exempt.id})

        self.assertTrue(line.tax_has_hashed_entries)
