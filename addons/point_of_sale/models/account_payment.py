# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    pos_payment_method_id = fields.Many2one("pos.payment.method", "POS Payment Method")
    force_outstanding_account_id = fields.Many2one(
        "account.account", "Forced Outstanding Account", check_company=True
    )
    pos_session_id = fields.Many2one(
        "pos.session", "POS Session", index="btree_not_null"
    )

    @api.depends("force_outstanding_account_id")
    def _compute_outstanding_account_id(self):
        """When force_outstanding_account_id is set, we use it as the outstanding_account_id."""
        super()._compute_outstanding_account_id()
        for payment in self:
            if payment.force_outstanding_account_id:
                payment.outstanding_account_id = payment.force_outstanding_account_id

    def _get_payment_method_codes_to_exclude(self):
        res = super()._get_payment_method_codes_to_exclude()

        # SEPA Credit Transfer requires a partner and bank account, but POS refunds
        # may have no customer. Exclude sepa_ct so account.payment are never created
        # with it, which would otherwise block session closing.
        if self.env["ir.module.module"]._get("account_iso20022").state == "installed":
            sepa_ct = self.env.ref(
                "account_iso20022.account_payment_method_sepa_ct",
                raise_if_not_found=False,
            )
            if (
                sepa_ct
                and "pos_payment" in self.env.context
                and sepa_ct.code not in res
            ):
                res.append(sepa_ct.code)
        return res
