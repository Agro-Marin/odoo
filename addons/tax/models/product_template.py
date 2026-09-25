from itertools import batched

from odoo import Command, api, fields, models
from odoo.libs.debug_log import DebugLog
from odoo.tools import format_amount

_debug = DebugLog(__name__)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    taxes_id = fields.Many2many(
        comodel_name="account.tax",
        relation="product_taxes_rel",
        column1="prod_id",
        column2="tax_id",
        string="Sales Taxes",
        default=lambda self: (
            self.env.companies.tax_config_id.account_sale_tax_id
            or self.env.companies.root_id.sudo().tax_config_id.account_sale_tax_id
        ),
        domain=[("type_tax_use", "=", "sale")],
        help="Default taxes used when selling the product",
    )
    tax_string = fields.Char(compute="_compute_tax_string")
    supplier_taxes_id = fields.Many2many(
        comodel_name="account.tax",
        relation="product_supplier_taxes_rel",
        column1="prod_id",
        column2="tax_id",
        string="Purchase Taxes",
        default=lambda self: (
            self.env.companies.tax_config_id.account_purchase_tax_id
            or self.env.companies.root_id.sudo().tax_config_id.account_purchase_tax_id
        ),
        domain=[("type_tax_use", "=", "purchase")],
        help="Default taxes used when buying the product",
    )

    @api.depends("taxes_id", "list_price")
    @api.depends_context("company")
    def _compute_tax_string(self):
        for record in self:
            record.tax_string = record._prepare_tax_string(record.list_price)

    @_debug.perf.timed
    def _prepare_tax_string(self, price):
        currency = self.currency_id
        res = self.taxes_id._filter_taxes_by_company(self.env.company).compute_all(
            price, product=self, partner=self.env["res.partner"]
        )
        joined = []
        included = res["total_included"]
        if currency.compare_amounts(included, price):
            joined.append(
                self.env._(
                    "%(amount)s Incl. Taxes",
                    amount=format_amount(self.env, included, currency),
                )
            )
        excluded = res["total_excluded"]
        if currency.compare_amounts(excluded, price):
            joined.append(
                self.env._(
                    "%(amount)s Excl. Taxes",
                    amount=format_amount(self.env, excluded, currency),
                )
            )
        if joined:
            tax_string = f"(= {', '.join(joined)})"
        else:
            tax_string = " "
        return tax_string

    @api.onchange("type")
    def _onchange_type(self):
        if self.type == "combo":
            self.taxes_id = False
            self.supplier_taxes_id = False
        return super()._onchange_type()

    def _clear_taxes_of_combo_products(self):
        combos = self.filtered(lambda product: product.type == "combo")
        if combos:
            combos.write(
                {"taxes_id": [Command.clear()], "supplier_taxes_id": [Command.clear()]}
            )

    def _force_default_tax_field(self, companies, company_tax_field, product_tax_field):
        default_taxes = companies.tax_config_id.mapped(company_tax_field)
        if not default_taxes:
            return
        links = [Command.link(t.id) for t in default_taxes]
        for sub_ids in batched(self.ids, self.env.cr.BATCH_SIZE, strict=False):
            chunk = self.browse(sub_ids)
            chunk.write({product_tax_field: links})
            chunk.invalidate_recordset([product_tax_field])

    def _force_default_tax(self, companies):
        self._force_default_tax_field(companies, "account_sale_tax_id", "taxes_id")
        self._force_default_tax_field(
            companies, "account_purchase_tax_id", "supplier_taxes_id"
        )

    @api.model_create_multi
    def create(self, vals_list):
        products = super().create(vals_list)
        products_without_company = products.filtered(lambda p: not p.company_id)
        if products_without_company:
            other_companies = (
                self.env["res.company"]
                .sudo()
                .search(["!", ("id", "child_of", self.env.companies.ids)])
            )
            _debug.logic(
                "default_taxes_forced",
                products=products_without_company,
                other_companies=other_companies,
            )
            if other_companies:
                products_without_company.sudo()._force_default_tax(other_companies)
        products.sudo()._clear_taxes_of_combo_products()
        return products

    def write(self, vals):
        result = super().write(vals)
        if "type" in vals:
            self.sudo()._clear_taxes_of_combo_products()
        return result

    def _get_list_price(self, price):
        self.check_singleton()
        taxes = self.taxes_id._filter_taxes_by_company(self.env.company)
        if not taxes:
            return super()._get_list_price(price)
        computed_price = taxes.compute_all(price, self.currency_id, product=self)
        total_included = computed_price["total_included"]

        if self.currency_id.compare_amounts(price, total_included) == 0:
            return total_included
        included_computed_price = taxes.with_context(
            force_price_include=True
        ).compute_all(price, self.currency_id, product=self)
        return included_computed_price["total_excluded"]
