from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_au_config_id = fields.Many2one(
        comodel_name="l10n_au.config",
        compute="_compute_l10n_au_config_id",
        search="_search_l10n_au_config_id",
    )

    l10n_au_is_gst_registered = fields.Boolean(
        related="l10n_au_config_id.l10n_au_is_gst_registered",
        readonly=False,
    )
    l10n_au_trading_name = fields.Char(
        related="l10n_au_config_id.l10n_au_trading_name",
        readonly=False,
    )

    def _search_l10n_au_config_id(self, operator, value):
        return self._search_config_link("l10n_au.config", operator, value)

    def _compute_l10n_au_config_id(self):
        self._compute_config_link("l10n_au_config_id")
