from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    l10n_latam_check_ids = fields.One2many(
        comodel_name="l10n_latam.check",
        inverse_name="outstanding_line_id",
        string="Checks",
    )

    def _filtered_amount_currency(self, amount_currency):
        return self.filtered(lambda line: line.amount_currency == amount_currency)
