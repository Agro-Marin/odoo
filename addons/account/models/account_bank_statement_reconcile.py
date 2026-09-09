from odoo import _, api, models


class AccountBankStatement(models.Model):
    _inherit = "account.bank.statement"

    def action_view_bank_reconcile_widget(self):
        self.check_singleton()
        return self.env[
            "account.bank.statement.line"
        ]._action_view_bank_reconciliation_widget(
            name=self.name,
            default_context={
                "search_default_statement_id": self.id,
                "search_default_journal_id": self.journal_id.id,
            },
            extra_domain=[("statement_id", "=", self.id)],
        )

    def action_view_journal_invalid_statements(self):
        self.check_singleton()
        return {
            "name": _("Invalid Bank Statements"),
            "type": "ir.actions.act_window",
            "res_model": "account.bank.statement",
            "view_mode": "list",
            "context": {
                "search_default_journal_id": self.journal_id.id,
                "search_default_invalid": True,
            },
        }

    def action_generate_attachment(self):
        ir_actions_report_sudo = self.env["ir.actions.report"].sudo()
        statement_report_action = self.env.ref(
            "account.action_report_account_statement"
        )
        for statement in self:
            statement_report = statement_report_action.sudo()
            content, _content_type = ir_actions_report_sudo._render_qweb_pdf(
                statement_report, res_ids=statement.ids
            )
            statement.attachment_ids |= self.env["ir.attachment"].create(
                {
                    "name": _("Bank Statement %s.pdf", statement.name)
                    if statement.name
                    else _("Bank Statement.pdf"),
                    "type": "binary",
                    "mimetype": "application/pdf",
                    "raw": content,
                    "res_model": statement._name,
                    "res_id": statement.id,
                }
            )
        return statement_report_action.report_action(docids=self)

    @api.model_create_multi
    def create(self, vals_list):
        statements = super().create(vals_list)
        if not self.env.context.get("skip_pdf_attachment_generation"):
            statements.filtered(
                lambda statement: (
                    statement.is_complete
                    and (
                        not statement.attachment_ids
                        or not any(
                            attachment.mimetype == "application/pdf"
                            for attachment in statement.attachment_ids
                        )
                    )
                )
            ).action_generate_attachment()

        return statements
