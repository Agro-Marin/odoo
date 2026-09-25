from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_sk_config_id = fields.Many2one(
        comodel_name="l10n_sk.config",
        compute="_compute_l10n_sk_config_id",
        search="_search_l10n_sk_config_id",
    )

    income_tax_id = fields.Char(
        related="l10n_sk_config_id.income_tax_id",
        readonly=False,
    )
    trade_registry = fields.Char(
        related="l10n_sk_config_id.trade_registry",
        readonly=False,
    )

    def _search_l10n_sk_config_id(self, operator, value):
        return self._search_config_link("l10n_sk.config", operator, value)

    def _compute_l10n_sk_config_id(self):
        self._compute_config_link("l10n_sk_config_id")
