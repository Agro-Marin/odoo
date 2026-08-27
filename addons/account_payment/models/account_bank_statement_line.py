import re

from odoo import models


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    def _get_partial_amounts(
        self, current_balance, move_line, open_amount_currency, open_balance
    ):
        # If a payment comes from a provider or is an iso/sepa payment, we don't want to allow a partial reconciliation on it
        # NOTE: this regex hardcodes the payment_method_code spelling owned by the
        # account_iso20022/l10n_*_sepa modules (out of this module's scope). If those
        # modules ever rename their codes, this silently stops matching - no error, just
        # a behaviour regression. A boolean capability flag on account.payment.method
        # (e.g. disallow_partial_reconcile) set by the owning modules would decouple this
        # from their exact code spelling.
        for payment in move_line.move_id.payment_ids:
            if (
                re.match(r"^iso20022.*|^sepa_ct$", payment.payment_method_code)
                or payment.payment_transaction_id
            ):
                return None

        return super()._get_partial_amounts(
            current_balance, move_line, open_amount_currency, open_balance
        )
