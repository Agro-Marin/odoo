from odoo import Command, api, models


class AccountAccount(models.Model):
    _inherit = "account.account"

    # `internal_group` values considered debit-normal for the MX
    # debit/credit-balance tag; every other value (liability, equity,
    # income, off) is considered credit-normal.
    _L10N_MX_DEBIT_INTERNAL_GROUPS = ("asset", "expense")

    def _l10n_mx_tag_accounts(self, accounts, debit_tag, credit_tag):
        # Classify by `internal_group` (derived from `account_type`)
        # rather than the account `code`: Mexico's COA group "7" ("Otros
        # ingresos y gastos") holds both debit-normal and credit-normal
        # accounts under the same leading digit, so a code-prefix lookup
        # misclassifies half of it.
        mx_accounts = accounts.filtered(
            lambda a: "MX" in a.company_ids.mapped("country_code")
        )
        debit_accounts = mx_accounts.filtered(
            lambda a: a.internal_group in self._L10N_MX_DEBIT_INTERNAL_GROUPS
        )
        credit_accounts = mx_accounts - debit_accounts
        if debit_accounts:
            debit_accounts.tag_ids = [
                Command.unlink(credit_tag.id),
                Command.link(debit_tag.id),
            ]
        if credit_accounts:
            credit_accounts.tag_ids = [
                Command.unlink(debit_tag.id),
                Command.link(credit_tag.id),
            ]

    @api.model_create_multi
    def create(self, vals_list):
        # EXTENDS account - ensure there is a tag on created MX accounts
        accounts = super().create(vals_list)
        debit_tag = self.env.ref(
            "l10n_mx.tag_debit_balance_account", raise_if_not_found=False
        )
        credit_tag = self.env.ref(
            "l10n_mx.tag_credit_balance_account", raise_if_not_found=False
        )
        if not debit_tag or not credit_tag:
            return accounts
        mx_account_no_tags = accounts.filtered(
            lambda a: not a.tag_ids & (credit_tag + debit_tag)
        )
        self._l10n_mx_tag_accounts(mx_account_no_tags, debit_tag, credit_tag)
        return accounts

    def write(self, vals):
        # EXTENDS account - a `code`/`account_type` change can move an
        # account across the debit/credit-balance boundary; keep the tag
        # in sync as long as it still only carries one of the two
        # auto-assigned tags (a tag_ids override beyond these two, set by
        # a user, is left untouched)
        res = super().write(vals)
        if "code" in vals or "account_type" in vals:
            debit_tag = self.env.ref(
                "l10n_mx.tag_debit_balance_account", raise_if_not_found=False
            )
            credit_tag = self.env.ref(
                "l10n_mx.tag_credit_balance_account", raise_if_not_found=False
            )
            if debit_tag and credit_tag:
                auto_tagged = self.filtered(
                    lambda a: a.tag_ids and a.tag_ids <= (debit_tag + credit_tag)
                )
                self._l10n_mx_tag_accounts(auto_tagged, debit_tag, credit_tag)
        return res
