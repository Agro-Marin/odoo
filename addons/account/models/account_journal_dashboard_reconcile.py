from odoo import models
from odoo.tools import formatLang


class AccountJournal(models.Model):
    _inherit = "account.journal"

    def action_view_reconcile(self):
        self.check_singleton()

        if self.type in ("bank", "cash", "credit"):
            return self.env[
                "account.bank.statement.line"
            ]._action_view_bank_reconciliation_widget(
                default_context={
                    "default_journal_id": self.id,
                    "search_default_journal_id": self.id,
                    "search_default_not_matched": True,
                },
            )
        else:
            return self.env["account.move.line"]._action_view_unreconciled()

    def action_view_to_check(self):
        self.check_singleton()
        return self.env[
            "account.bank.statement.line"
        ]._action_view_bank_reconciliation_widget(
            default_context={
                "search_default_to_check": True,
                "search_default_journal_id": self.id,
                "default_journal_id": self.id,
            },
        )

    def action_view_bank_transactions(self):
        self.check_singleton()
        return self.env[
            "account.bank.statement.line"
        ]._action_view_bank_reconciliation_widget(
            default_context={
                "search_default_journal_id": self.id,
                "default_journal_id": self.id,
            },
            kanban_first=False,
        )

    def action_view_reconcile_statement(self):
        return self.env[
            "account.bank.statement.line"
        ]._action_view_bank_reconciliation_widget(
            default_context={
                "search_default_statement_id": self.env.context.get("statement_id"),
                "default_journal_id": self.id,
            },
        )

    def open_invalid_statements_action(self):
        self.check_singleton()
        if self.env["account.bank.statement"].search(
            [("journal_id", "=", self.id), ("first_line_index", "=", False)], limit=1
        ):
            return super().open_invalid_statements_action()
        return self.env[
            "account.bank.statement.line"
        ]._action_view_bank_reconciliation_widget(
            extra_domain=[("line_ids.account_id", "=", self.default_account_id.id)],
            default_context={
                "default_journal_id": self.id,
                "search_default_journal_id": self.id,
                "search_default_invalid_statement": True,
            },
            kanban_first=False,
        )

    def open_action(self):
        if self.type in ("bank", "cash", "credit") and not self.env.context.get(
            "action_name"
        ):
            self.check_singleton()
            return self.env[
                "account.bank.statement.line"
            ]._action_view_bank_reconciliation_widget(
                default_context={
                    "default_journal_id": self.id,
                    "search_default_journal_id": self.id,
                },
            )
        return super().open_action()

    def get_total_journal_amount(self):
        balance = ""
        if self.exists() and any(
            company in self.company_id._get_accessible_branches()
            for company in self.env.companies
        ):
            balance = formatLang(
                self.env,
                self.current_statement_balance,
                currency_obj=self.currency_id or self.company_id.sudo().currency_id,
            )
        return {
            "balance_amount": balance,
            "has_invalid_statements": self.has_invalid_statements,
        }
