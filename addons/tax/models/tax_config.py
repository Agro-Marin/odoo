from odoo import api, fields, models
from odoo.fields import Domain


class TaxConfig(models.Model):
    _name = "tax.config"
    _description = "A company's tax configuration"
    _inherit = ["mixin.company.config"]

    account_fiscal_country_id = fields.Many2one(
        comodel_name="res.country",
        string="Fiscal Country",
        compute="_compute_account_fiscal_country_id",
        store=True,
        readonly=False,
        help="The country to use the tax reports from for this company",
    )
    account_price_include = fields.Selection(
        selection=[("tax_included", "Tax Included"), ("tax_excluded", "Tax Excluded")],
        string="Default Sales Price Include",
        default="tax_excluded",
        required=True,
        help="Default on whether the sales price used on the product and invoices with this Company includes its taxes.",
    )
    tax_calculation_rounding_method = fields.Selection(
        selection=[
            ("round_globally", "Round per Tax"),
            ("round_per_line", "Round per Line"),
        ],
        default="round_globally",
    )
    account_sale_tax_id = fields.Many2one(
        comodel_name="account.tax",
        string="Default Sale Tax",
        check_company=True,
    )
    account_purchase_tax_id = fields.Many2one(
        comodel_name="account.tax",
        string="Default Purchase Tax",
        check_company=True,
    )
    domestic_fiscal_position_id = fields.Many2one(
        comodel_name="account.fiscal.position",
        compute="_compute_domestic_fiscal_position_id",
    )
    fiscal_position_ids = fields.One2many(
        comodel_name="account.fiscal.position",
        compute="_compute_fiscal_position_ids",
    )
    multi_vat_foreign_country_ids = fields.Many2many(
        comodel_name="res.country",
        string="Foreign VAT countries",
        compute="_compute_multi_vat_foreign_country_ids",
        help="Countries for which the company has a VAT number",
    )

    @api.depends("company_id.country_id")
    def _compute_account_fiscal_country_id(self):
        for config in self:
            if not config.account_fiscal_country_id:
                config.account_fiscal_country_id = config.company_id.country_id

    @api.depends("company_id")
    def _compute_fiscal_position_ids(self):
        positions = self.env["account.fiscal.position"].search(
            [("company_id", "in", self.company_id.ids)]
        )
        by_company = positions.grouped("company_id")
        for config in self:
            config.fiscal_position_ids = by_company.get(
                config.company_id, self.env["account.fiscal.position"]
            )

    @api.depends("company_id.country_id")
    def _compute_domestic_fiscal_position_id(self):
        for config in self:
            country = config.company_id.country_id
            potential_domestic_fps = config.fiscal_position_ids.filtered_domain(
                Domain("country_id", "=", country.id)
                | Domain(
                    [
                        ("country_id", "=", False),
                        ("country_group_id", "in", country.country_group_ids.ids),
                    ]
                ),
            ).sorted(lambda fp: (fp.sequence, fp.country_id.id or float("inf")))
            config.domestic_fiscal_position_id = potential_domestic_fps[:1]

    def _get_foreign_vat_countries_per_company(self, companies):
        FiscalPosition = self.env["account.fiscal.position"]
        return {
            company.id: self.env["res.country"].browse(filter(None, country_ids))
            for company, country_ids in FiscalPosition._read_group(
                domain=[
                    *FiscalPosition._check_company_domain(companies),
                    ("foreign_vat", "!=", False),
                ],
                groupby=["company_id"],
                aggregates=["country_id:array_agg"],
            )
        }

    @api.depends("company_id")
    def _compute_multi_vat_foreign_country_ids(self):
        countries_per_company = self._get_foreign_vat_countries_per_company(
            self.company_id
        )
        for config in self:
            config.multi_vat_foreign_country_ids = countries_per_company.get(
                config.company_id.id, self.env["res.country"]
            )
