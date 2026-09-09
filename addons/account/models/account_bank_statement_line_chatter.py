from dateutil.relativedelta import relativedelta

from odoo import _, fields, models


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    def _get_last_5_minutes_messages(self, body):
        self.check_singleton()
        # `=` rather than `ilike`: the needle is the note body itself, and every `_`
        # or `%` it contains is a LIKE wildcard, so an unrelated message that merely
        # fits the pattern would silence a real note. Verified that both the SQL and
        # the in-memory path wildcard those characters.
        #
        # Searched rather than filtered off `move_id.message_ids`, which would load
        # the move's whole chatter to look at the last five minutes of it.
        return self.env["mail.message"].search(
            [
                ("model", "=", self.move_id._name),
                ("res_id", "=", self.move_id.id),
                ("author_id", "=", self.env.user.partner_id.id),
                ("create_date", ">=", fields.Datetime.now() - relativedelta(minutes=5)),
                ("body", "=", body),
            ],
            limit=1,
        )

    def _post_matching_note(self, body):
        self.check_singleton()
        if self._get_last_5_minutes_messages(body=body):
            return
        self.move_id.message_post(body=body, author_id=self.env.user.partner_id.id)

    def _post_matching_done_confirmation(self):
        self.check_singleton()
        if not self.is_reconciled:
            return
        body = _("Matching done")
        if reconcile_model := self.move_id.line_ids.reconcile_model_id:
            body += _(
                " - %(reconcile_model_name)s",
                reconcile_model_name=", ".join(reconcile_model.mapped("name")),
            )
        self._post_matching_note(body)

    def _post_matching_unreconciled(self):
        self.check_singleton()
        if self.is_reconciled:
            return
        self._post_matching_note(_("Matching unreconciled"))

    def _create_payment_with_move_from_invoice(self, move_id):
        return (
            self.env["account.payment.register"]
            .with_context(
                active_model="account.move",
                active_ids=move_id.ids,
                force_payment_move=True,
            )
            .create(
                {
                    "payment_date": self.date,
                }
            )
            ._create_payments()
        )

    def _reconcile_with_payments(self, payments, amls_to_create, reconciled_lines=None):
        self.check_singleton()
        has_exchange_diff = False
        if reconciled_lines:
            for reconciled_line, aml_to_create in zip(
                reconciled_lines, amls_to_create, strict=True
            ):
                exchange_diff_balance = self._lines_get_account_balance_exchange_diff(
                    reconciled_line.currency_id,
                    reconciled_line.amount_residual,
                    reconciled_line.amount_residual_currency,
                )
                has_exchange_diff = (
                    has_exchange_diff
                    or not reconciled_line.currency_id.is_zero(exchange_diff_balance)
                )
                new_balance = -(reconciled_line.amount_residual + exchange_diff_balance)

                aml_to_create["balance"] = new_balance

        self.with_context(
            no_exchange_difference_no_recursive=not has_exchange_diff
        )._add_move_line_to_statement_line_move(amls_to_create)
        if payments_to_validate := payments.filtered(
            lambda p: (
                not p.move_id
                and p.state in self.env["account.payment"]._valid_payment_states()
            )
        ):
            payments_to_validate.action_validate()
