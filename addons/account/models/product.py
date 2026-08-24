import logging
from difflib import SequenceMatcher
from itertools import batched

from odoo import Command, _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.models import PREFETCH_MAX
from odoo.tools import SQL, format_amount

_logger = logging.getLogger(__name__)


def name_length_band(searched_length, threshold):
    """Lengths a candidate name must fall within to be able to reach `threshold`.

    `SequenceMatcher(a, b).ratio()` is `2 * matches / (len(a) + len(b))` and
    `matches <= min(len(a), len(b))`, so anything outside this band is provably
    below the threshold. Testing two integers is far cheaper than the quadratic
    comparison it replaces.
    """
    return (
        searched_length * threshold / (2 - threshold),
        searched_length * (2 - threshold) / threshold,
    )


DEFAULT_NAME_SIMILARITY_THRESHOLD = 0.9

ACCOUNT_DOMAIN = "[('account_type', 'not in', ('asset_receivable','liability_payable','asset_cash','liability_credit_card','off_balance'))]"


class ProductTemplate(models.Model):
    _name = "product.template"
    _inherit = ["product.template", "mixin.fiscal.country.codes"]

    taxes_id = fields.Many2many(
        "account.tax",
        "product_taxes_rel",
        "prod_id",
        "tax_id",
        string="Sales Taxes",
        help="Default taxes used when selling the product",
        domain=[("type_tax_use", "=", "sale")],
        default=lambda self: (
            self.env.companies.account_sale_tax_id
            or self.env.companies.root_id.sudo().account_sale_tax_id
        ),
    )
    tax_string = fields.Char(
        compute="_compute_tax_string",
    )
    supplier_taxes_id = fields.Many2many(
        "account.tax",
        "product_supplier_taxes_rel",
        "prod_id",
        "tax_id",
        string="Purchase Taxes",
        help="Default taxes used when buying the product",
        domain=[("type_tax_use", "=", "purchase")],
        default=lambda self: (
            self.env.companies.account_purchase_tax_id
            or self.env.companies.root_id.sudo().account_purchase_tax_id
        ),
    )
    property_account_income_id = fields.Many2one(
        "account.account",
        company_dependent=True,
        ondelete="restrict",
        string="Income Account",
        domain=ACCOUNT_DOMAIN,
        help="Keep this field empty to use the default value from the product category.",
    )
    property_account_expense_id = fields.Many2one(
        "account.account",
        company_dependent=True,
        ondelete="restrict",
        string="Expense Account",
        domain=ACCOUNT_DOMAIN,
        help="Keep this field empty to use the default value from the product category. If anglo-saxon accounting with automated valuation method is configured, the expense account on the product category will be used.",
    )
    account_tag_ids = fields.Many2many(
        string="Account Tags",
        comodel_name="account.account.tag",
        domain="[('applicability', '=', 'products')]",
        help="Tags to be set on the base and tax journal items created for this product.",
    )

    def _get_product_accounts(self, fiscal_pos=None):
        self.ensure_one()
        # Every tier resolves against `env.company`: the caller posts the result
        # into that company's journal, and `check_company` already forbids using
        # a company-bound product anywhere else.
        company = self.env.company
        accounts = {
            "income": (
                self.property_account_income_id
                or self._get_category_account("property_account_income_categ_id")
                or company.income_account_id
            ),
            "expense": (
                self.property_account_expense_id
                or self._get_category_account("property_account_expense_categ_id")
                or company.expense_account_id
            ),
        }
        return self._map_product_accounts(accounts, fiscal_pos)

    def _map_product_accounts(self, accounts, fiscal_pos):
        # Subclasses add keys of their own, and not all of them are accounts:
        # `stock_account` contributes a journal, which a fiscal position must
        # not rewrite. Each contributor decides by calling this on its own keys.
        if not fiscal_pos:
            return accounts
        return {
            key: fiscal_pos.map_account(value)
            if value._name == "account.account"
            else value
            for key, value in accounts.items()
        }

    def _get_category_account(self, field_name):
        categ = self.categ_id
        while categ:
            account = categ[field_name]
            if account:
                return account
            categ = categ.parent_id
        return self.env["account.account"]

    @api.depends("company_id")
    def _compute_fiscal_country_codes(self):
        return super()._compute_fiscal_country_codes()

    def _get_fiscal_country_companies(self):
        return self.company_id or super()._get_fiscal_country_companies()

    @api.depends("taxes_id", "list_price")
    @api.depends_context("company")
    def _compute_tax_string(self):
        for record in self:
            record.tax_string = record._prepare_tax_string(record.list_price)

    def _prepare_tax_string(self, price):
        currency = self.currency_id
        res = self.taxes_id._filter_taxes_by_company(self.env.company).compute_all(
            price, product=self, partner=self.env["res.partner"]
        )
        joined = []
        included = res["total_included"]
        if currency.compare_amounts(included, price):
            joined.append(
                _(
                    "%(amount)s Incl. Taxes",
                    amount=format_amount(self.env, included, currency),
                )
            )
        excluded = res["total_excluded"]
        if currency.compare_amounts(excluded, price):
            joined.append(
                _(
                    "%(amount)s Excl. Taxes",
                    amount=format_amount(self.env, excluded, currency),
                )
            )
        if joined:
            tax_string = f"(= {', '.join(joined)})"
        else:
            tax_string = " "
        return tax_string

    def _check_uom_not_used_on_a_posted_entry(self):
        if not self:
            return
        self.env["account.move.line"].flush_model(["product_id", "parent_state"])
        self.env["product.product"].flush_model(["product_tmpl_id"])
        self.env.cr.execute(
            """
            SELECT prod_template.id
              FROM account_move_line line
              JOIN product_product prod_variant ON line.product_id = prod_variant.id
              JOIN product_template prod_template ON prod_variant.product_tmpl_id = prod_template.id
             WHERE prod_template.id = ANY(%s)
               AND line.parent_state = 'posted'
             LIMIT 1
        """,
            [list(self.ids)],
        )
        row = self.env.cr.fetchone()
        if row:
            raise ValidationError(
                _(
                    "%(product)s is already used on posted journal entries.\n"
                    "To change its Unit of Measure, archive it and create a new product.",
                    product=self.browse(row[0]).display_name,
                )
            )

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
        default_taxes = companies.mapped(company_tax_field)
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
            if other_companies:
                products_without_company.sudo()._force_default_tax(other_companies)
        products.sudo()._clear_taxes_of_combo_products()
        return products

    def write(self, vals):
        # A posted journal item stores its quantity in its own unit; changing the
        # product's unit afterwards silently reinterprets every one of them. The
        # check belongs on the transition, so a write that leaves the unit alone
        # -- including one that rewrites the same value -- stays allowed.
        if "uom_id" in vals:
            self.filtered(
                lambda product: product.uom_id.id != vals["uom_id"]
            )._check_uom_not_used_on_a_posted_entry()
        result = super().write(vals)
        if "type" in vals:
            self.sudo()._clear_taxes_of_combo_products()
        return result

    def _get_list_price(self, price):
        self.ensure_one()
        # `taxes_id` holds every company's default sale tax on purpose (see
        # `_force_default_tax`), so the active company's subset is the only one
        # that may be stripped from a price quoted in that company.
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


class ProductProduct(models.Model):
    _inherit = "product.product"

    tax_string = fields.Char(compute="_compute_tax_string")

    def _get_product_accounts(self, fiscal_pos=None):
        return self.product_tmpl_id._get_product_accounts(fiscal_pos=fiscal_pos)

    def _get_tax_included_unit_price(
        self,
        company,
        currency,
        document_date,
        document_type,
        is_refund_document=False,
        product_uom_id=None,
        product_currency=None,
        product_price_unit=None,
        product_taxes=None,
        fiscal_position=None,
    ):
        self.ensure_one()
        company.ensure_one()

        if not document_type:
            raise ValueError("document_type is required")

        if product_uom_id is None:
            product_uom_id = self.uom_id
        if not product_currency:
            if document_type == "sale":
                product_currency = self.currency_id
            elif document_type == "purchase":
                product_currency = company.currency_id
        if product_price_unit is None:
            if document_type == "sale":
                product_price_unit = self.with_company(company).lst_price
            elif document_type == "purchase":
                product_price_unit = self.with_company(company).standard_price
            else:
                return 0.0
        if product_taxes is None:
            if document_type == "sale":
                product_taxes = self.taxes_id
            elif document_type == "purchase":
                product_taxes = self.supplier_taxes_id
        if product_taxes:
            product_taxes = product_taxes._filter_taxes_by_company(company)
        if product_uom_id and self.uom_id != product_uom_id:
            product_price_unit = self.uom_id._compute_price(
                product_price_unit, product_uom_id
            )

        if product_taxes and fiscal_position:
            product_price_unit = self._get_tax_included_unit_price_from_price(
                product_price_unit,
                product_taxes,
                fiscal_position=fiscal_position,
            )

        if product_currency and currency != product_currency:
            product_price_unit = product_currency._convert(
                product_price_unit, currency, company, document_date, round=False
            )

        return product_price_unit

    def _get_tax_included_unit_price_from_price(
        self,
        product_price_unit,
        product_taxes,
        fiscal_position=None,
        product_taxes_after_fp=None,
    ):
        if not product_taxes:
            return product_price_unit

        if product_taxes_after_fp is None:
            if not fiscal_position:
                return product_price_unit

            product_taxes_after_fp = fiscal_position.map_tax(product_taxes)

        return product_taxes._adapt_price_unit_to_another_taxes(
            price_unit=product_price_unit,
            product=self,
            original_taxes=product_taxes,
            new_taxes=product_taxes_after_fp,
        )

    @api.depends("lst_price", "product_tmpl_id", "taxes_id")
    @api.depends_context("company")
    def _compute_tax_string(self):
        for record in self:
            record.tax_string = record.product_tmpl_id._prepare_tax_string(
                record.lst_price
            )

    def _get_import_criteria_from_barcode(self, product_values):
        barcode = product_values.get("barcode")
        if barcode:
            return {"criteria": [{"domain": [("barcode", "=", barcode)]}]}
        return None

    def _get_import_criteria_from_default_code(self, product_values):
        default_code = product_values.get("default_code")
        if default_code:
            return {"criteria": [{"domain": [("default_code", "=", default_code)]}]}
        return None

    def _get_product_name_similarity_threshold(self):
        default = DEFAULT_NAME_SIMILARITY_THRESHOLD
        raw = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("account.product_name_similarity_threshold", default)
        )
        try:
            threshold = float(raw)
        except TypeError, ValueError:
            _logger.warning(
                "account.product_name_similarity_threshold is not a number (%r),"
                " falling back to %s",
                raw,
                default,
            )
            return default
        if not 0.0 < threshold <= 1.0:
            _logger.warning(
                "account.product_name_similarity_threshold must be within ]0, 1]"
                " (got %s), falling back to %s",
                threshold,
                default,
            )
            return default
        return threshold

    def _get_name_recall_domain(self, name):
        """Candidates worth scoring for `name`.

        A `name ilike` prefilter can only return names that *contain* the
        searched one, so it can never offer the near-miss the scoring exists to
        catch. Trigram similarity can, and it is what the GIN index on
        `product_template.name` is built for.
        """
        if not self.pool.has_trigram:
            return Domain("name", "ilike", name)

        def similar_name(model, alias, query):
            raw_name = model._fields["name"].to_sql(
                model.with_context(prefetch_langs=True), alias
            )
            unaccent = model.env.registry.unaccent
            return SQL(
                "%s %% %s",
                unaccent(SQL("jsonb_path_query_array(%s, '$.*')::text", raw_name)),
                unaccent(SQL("%s", name)),
            )

        return Domain("product_tmpl_id", "any", Domain.custom(to_sql=similar_name))

    def _get_product_by_name_similarity(self, name, domain):
        threshold = self._get_product_name_similarity_threshold()
        shortest, longest = name_length_band(len(name), threshold)
        candidate_ids = self.search(
            Domain.AND([self._get_name_recall_domain(name), domain])
        ).ids
        lowered_name = name.lower()
        best_product = self.browse()
        best_ratio = 0.0
        for batch_ids in batched(candidate_ids, PREFETCH_MAX, strict=False):
            products = self.browse(batch_ids)
            products.fetch(["product_tmpl_id"])
            products.product_tmpl_id.fetch(["name"])
            for product in products:
                candidate = product.name
                if not shortest <= len(candidate) <= longest:
                    continue
                ratio = SequenceMatcher(None, lowered_name, candidate.lower()).ratio()
                if ratio >= threshold and ratio > best_ratio:
                    best_ratio = ratio
                    best_product = product
            products.invalidate_recordset()
        return best_product

    def _get_import_criteria_from_name(self, product_values):
        name = (product_values.get("name") or "").split("\n", 1)[0]
        if not name:
            return None
        return {
            "criteria": [
                {"domain": [("name", "=", name)]},
                {
                    "search_method": lambda domain: (
                        self._get_product_by_name_similarity(name, domain)
                    )
                },
            ]
        }

    def _get_import_product_classification_specs(self):
        """Classification codes an inbound document may carry, contributed by
        whichever module defines the field and its comodel.
        """
        return []

    def _get_import_product_classification_domain(self, product_values):
        extra_domain = []
        order_fields = []
        for spec in self._get_import_product_classification_specs():
            code = product_values.get(spec["value_key"])
            field = spec["field"]
            if not code:
                continue
            record = self.env[spec["comodel"]].search(
                [(spec["code_field"], "=", code)], limit=1
            )
            if not record:
                continue
            extra_domain.append((field, "in", (record.id, False)))
            order_fields.append(field)
        return extra_domain, order_fields

    @api.model
    def _get_product_from_search_plan(
        self, search_plan, company, product_values, extra_domain=None
    ):
        domain = Domain.OR(
            [
                [*self._check_company_domain(company), ("company_id", "!=", False)],
                [("company_id", "=", False)],
            ]
        )
        if extra_domain:
            domain = Domain.AND([domain, extra_domain])
        classification_domain, order_fields = (
            self._get_import_product_classification_domain(product_values)
        )
        domain = Domain.AND([domain, classification_domain])
        order = ", ".join(["company_id", *order_fields, "id DESC"])

        for plan in search_plan:
            plan_values = plan(product_values)
            if not plan_values:
                continue
            for criteria in plan_values["criteria"]:
                if criteria_domain := criteria.get("domain"):
                    product = self.search(
                        Domain.AND([domain, list(criteria_domain)]),
                        order=order,
                        limit=1,
                    )
                elif search_method := criteria.get("search_method"):
                    product = search_method(domain)
                else:
                    continue
                if product:
                    return product
        return self.browse()

    def _get_import_product_search_plan(self):
        return [
            (5, self._get_import_criteria_from_barcode),
            (10, self._get_import_criteria_from_default_code),
            (15, self._get_import_criteria_from_name),
        ]

    def _get_imported_product(self, company=None, extra_domain=None, **product_vals):
        return self._get_product_from_search_plan(
            search_plan=[
                method
                for _priority, method in sorted(
                    self._get_import_product_search_plan(),
                    key=lambda plan: plan[0],
                )
            ],
            company=company or self.env.company,
            product_values=product_vals,
            extra_domain=extra_domain,
        )
