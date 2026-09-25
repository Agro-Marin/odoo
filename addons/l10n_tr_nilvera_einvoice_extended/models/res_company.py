from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"
    _inherits_sudo_fields = ("l10n_tr_tax_office_id",)

    l10n_tr_nilvera_einvoice_extended_config_id = fields.Many2one(
        comodel_name="l10n_tr_nilvera_einvoice_extended.config",
        compute="_compute_l10n_tr_nilvera_einvoice_extended_config_id",
        search="_search_l10n_tr_nilvera_einvoice_extended_config_id",
    )

    def _search_l10n_tr_nilvera_einvoice_extended_config_id(self, operator, value):
        return self._search_config_link(
            "l10n_tr_nilvera_einvoice_extended.config", operator, value
        )

    def _compute_l10n_tr_nilvera_einvoice_extended_config_id(self):
        self._compute_config_link("l10n_tr_nilvera_einvoice_extended_config_id")
