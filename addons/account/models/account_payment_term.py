from odoo import api, models
from odoo.exceptions import UserError
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class AccountPaymentTerm(models.Model):
    _name = "account.payment.term"
    _inherit = ["account.payment.term", "mixin.fiscal.country.codes"]

    @api.depends("company_id")
    def _compute_fiscal_country_codes(self):
        return super()._compute_fiscal_country_codes()

    def _get_fiscal_country_companies(self):
        return self.company_id or super()._get_fiscal_country_companies()

    @api.ondelete(at_uninstall=False)
    @_debug.perf.timed
    def _unlink_except_referenced_terms(self):
        _debug.lifecycle("_unlink_except_referenced_terms", records=self)
        if (
            self.env["account.move"]
            .sudo()
            .search_count([("invoice_payment_term_id", "in", self.ids)], limit=1)
        ):
            raise UserError(
                self.env._(
                    "Uh-oh! Those payment terms are quite popular and can't be deleted since there are still some records referencing them. How about archiving them instead?"
                )
            )
