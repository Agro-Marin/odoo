from odoo import api, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain

from ..tools import debug_log as dbg


class AccountConfig(models.Model):
    _inherit = "account.config"

    @api.constrains(
        "fiscalyear_lock_date",
        "tax_lock_date",
        "sale_lock_date",
        "hard_lock_date",
    )
    def _check_lock_dates_pos_sessions(self):
        pos_session_model = self.env["pos.session"].sudo()
        for config in self.with_context(ignore_exceptions=True):
            fiscal_lock_date = max(
                config.user_fiscalyear_lock_date,
                config.user_hard_lock_date,
            )
            sessions_in_period = pos_session_model.search(
                Domain("company_id", "child_of", config.company_id.id)
                & Domain("state", "!=", "closed")
                & Domain.OR(
                    (
                        Domain("start_at", "<=", fiscal_lock_date),
                        Domain("start_at", "<=", config.user_tax_lock_date),
                        Domain("config_id.journal_id.type", "=", "sale")
                        & Domain("start_at", "<=", config.user_sale_lock_date),
                    )
                )
            )
            if sessions_in_period:
                dbg.logic.debug(
                    "lock date on company %s refused by open sessions %s",
                    config.company_id.id,
                    dbg.rec(sessions_in_period),
                )
                raise ValidationError(
                    self.env._(
                        "Please close all the point of sale sessions in this period before closing it. Open sessions are: %s ",
                        ", ".join(sessions_in_period.mapped("name")),
                    )
                )
