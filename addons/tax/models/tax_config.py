from odoo import api, fields, models


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

    @api.depends("company_id.country_id")
    def _compute_account_fiscal_country_id(self):
        for config in self:
            if not config.account_fiscal_country_id:
                config.account_fiscal_country_id = config.company_id.country_id
