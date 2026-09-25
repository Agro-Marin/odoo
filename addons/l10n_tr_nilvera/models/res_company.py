from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"
    _CREDENTIAL_FIELDS = {
        "l10n_tr_nilvera_api_key": "l10n_tr_nilvera_api_key",
    }

    l10n_tr_nilvera_config_id = fields.Many2one(
        comodel_name="l10n_tr_nilvera.config",
        compute="_compute_l10n_tr_nilvera_config_id",
        search="_search_l10n_tr_nilvera_config_id",
    )

    l10n_tr_nilvera_api_key = fields.Char(
        string="Nilvera API key",
        compute="_compute_credential_doors",
        inverse="_inverse_credential_doors",
        groups="base.group_system",
    )

    def _search_l10n_tr_nilvera_config_id(self, operator, value):
        return self._search_config_link("l10n_tr_nilvera.config", operator, value)

    def _compute_l10n_tr_nilvera_config_id(self):
        self._compute_config_link("l10n_tr_nilvera_config_id")
