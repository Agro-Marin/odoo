from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_nl_config_id = fields.Many2one(
        comodel_name="l10n_nl.config",
        compute="_compute_l10n_nl_config_id",
        search="_search_l10n_nl_config_id",
    )

    def _search_l10n_nl_config_id(self, operator, value):
        return self._search_config_link("l10n_nl.config", operator, value)

    def _compute_l10n_nl_config_id(self):
        self._compute_config_link("l10n_nl_config_id")
