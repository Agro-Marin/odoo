from odoo import api, fields, models


class MixinFiscalCountryCodes(models.AbstractModel):
    _name = "mixin.fiscal.country.codes"
    _description = "Fiscal Country Codes"

    fiscal_country_codes = fields.Char(compute="_compute_fiscal_country_codes")

    def _get_fiscal_country_companies(self):
        """Companies whose fiscal country decides what this record may show.

        A record carrying its own `company_id` answers for that company alone;
        anything shared answers for whichever companies are active.
        """
        self.ensure_one()
        return self.env.companies

    @api.depends_context("allowed_company_ids")
    def _compute_fiscal_country_codes(self):
        for record in self:
            record.fiscal_country_codes = ",".join(
                sorted(
                    record._get_fiscal_country_companies().mapped(
                        "account_fiscal_country_id.code"
                    )
                )
            )
