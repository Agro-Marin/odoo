from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    tax_config_id = fields.Many2one(
        comodel_name="tax.config",
        compute="_compute_tax_config_id",
        search="_search_tax_config_id",
    )
    account_fiscal_country_id = fields.Many2one(
        related="tax_config_id.account_fiscal_country_id",
    )
    tax_calculation_rounding_method = fields.Selection(
        related="tax_config_id.tax_calculation_rounding_method",
    )

    def _search_tax_config_id(self, operator, value):
        return self._search_config_link("tax.config", operator, value)

    def _compute_tax_config_id(self):
        configs = self.env["tax.config"]._for_each(self)
        by_company = dict(zip(configs.mapped("company_id").ids, configs, strict=True))
        for company in self:
            company.tax_config_id = by_company.get(company.id, False)
