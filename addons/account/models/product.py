from difflib import SequenceMatcher
from itertools import batched

from odoo import Command, _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.libs.constants import PREFETCH_MAX
from odoo.tools import format_amount, frozendict

ACCOUNT_DOMAIN = "[('account_type', 'not in', ('asset_receivable','liability_payable','asset_cash','liability_credit_card','off_balance'))]"


class ProductCategory(models.Model):
    _inherit = "product.category"

    property_account_income_categ_id = fields.Many2one(
        "account.account",
        company_dependent=True,
        string="Income Account",
        domain=ACCOUNT_DOMAIN,
        help="This account will be used when validating a customer invoice.",
        tracking=True,
        ondelete="restrict",
    )
    property_account_expense_categ_id = fields.Many2one(
        "account.account",
        company_dependent=True,
        string="Expense Account",
        domain=ACCOUNT_DOMAIN,
        help="The expense is accounted for when a vendor bill is validated, except in anglo-saxon accounting with perpetual inventory valuation in which case the expense (Cost of Goods Sold account) is recognized at the customer invoice validation.",
        tracking=True,
        ondelete="restrict",
    )


# ----------------------------------------------------------
# Products
# ----------------------------------------------------------


class ProductTemplate(models.Model):
    _inherit = "product.template"

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
    tax_string = fields.Char(compute="_compute_tax_string")
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
    fiscal_country_codes = fields.Char(compute="_compute_fiscal_country_codes")

    def _get_product_accounts(self):
        self.ensure_one()
        return {
            "income": (
                self.property_account_income_id
                or self._get_category_account("property_account_income_categ_id")
                or (self.company_id or self.env.company).income_account_id
            ),
            "expense": (
                self.property_account_expense_id
                or self._get_category_account("property_account_expense_categ_id")
                or (self.company_id or self.env.company).expense_account_id
            ),
        }

    def _get_category_account(self, field_name):
        """Return the first account defined on the product category hierarchy for ``field_name``."""
        categ = self.categ_id
        while categ:
            account = categ[field_name]
            if account:
                return account
            categ = categ.parent_id
        return self.env["account.account"]

    def get_product_accounts(self, fiscal_pos=None):
        return {
            key: (fiscal_pos or self.env["account.fiscal.position"]).map_account(
                account
            )
            for key, account in self._get_product_accounts().items()
        }

    @api.depends("company_id")
    @api.depends_context("allowed_company_ids")
    def _compute_fiscal_country_codes(self):
        for record in self:
            allowed_companies = record.company_id or self.env.companies
            record.fiscal_country_codes = ",".join(
                allowed_companies.mapped("account_fiscal_country_id.code")
            )

    @api.depends("taxes_id", "list_price")
    @api.depends_context("company")
    def _compute_tax_string(self):
        for record in self:
            record.tax_string = record._construct_tax_string(record.list_price)

    def _construct_tax_string(self, price):
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

    @api.constrains("uom_id")
    def _check_uom_not_in_invoice(self):
        self.env["product.template"].flush_model(["uom_id"])
        self.env.cr.execute(
            """
            SELECT prod_template.id
              FROM account_move_line line
              JOIN product_product prod_variant ON line.product_id = prod_variant.id
              JOIN product_template prod_template ON prod_variant.product_tmpl_id = prod_template.id
              JOIN uom_uom template_uom ON prod_template.uom_id = template_uom.id
              JOIN uom_uom line_uom ON line.product_uom_id = line_uom.id
             WHERE prod_template.id = ANY(%s)
               AND line.parent_state = 'posted'
               AND template_uom.id != line_uom.id
             LIMIT 1
        """,
            [list(self.ids)],
        )
        if self.env.cr.fetchone():
            raise ValidationError(
                _(
                    "This product is already being used in posted Journal Entries.\n"
                    "If you want to change its Unit of Measure, please archive this product and create a new one."
                )
            )

    @api.onchange("type")
    def _onchange_type(self):
        if self.type == "combo":
            self.taxes_id = False
            self.supplier_taxes_id = False
        return super()._onchange_type()

    def _force_default_tax_field(self, companies, company_tax_field, product_tax_field):
        """Add ``companies``' default taxes (``company_tax_field``) onto every
        product in ``self`` (``product_tax_field``), writing in batches.
        """
        # ``mapped`` on a Many2one already drops empty relations, so no
        # ``filtered`` prefilter is needed to skip companies without a default.
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
        # A product without a company is shared across every company and must
        # therefore also carry the default taxes of the companies the current
        # user may not see. Only look those companies up when such a product was
        # actually created -- the common case (every product has a company) must
        # not pay for a res.company search it won't use.
        products_without_company = products.filtered(lambda p: not p.company_id)
        if products_without_company:
            # sudo(): we need every other company's default taxes, which the
            # user may not have access to.
            other_companies = (
                self.env["res.company"]
                .sudo()
                .search(["!", ("id", "child_of", self.env.companies.ids)])
            )
            if other_companies:
                products_without_company.sudo()._force_default_tax(other_companies)
        return products

    def _get_list_price(self, price):
        """Get the product sales price from a public price based on taxes defined on the product"""
        self.ensure_one()
        if not self.taxes_id:
            return super()._get_list_price(price)
        # Pass ``product=self`` so product-sensitive taxes compute against this
        # product, matching ``_construct_tax_string``.
        computed_price = self.taxes_id.compute_all(
            price, self.currency_id, product=self
        )
        total_included = computed_price["total_included"]

        if self.currency_id.compare_amounts(price, total_included) == 0:
            # Tax is configured as price included
            return total_included
        # calculate base from tax
        included_computed_price = self.taxes_id.with_context(
            force_price_include=True
        ).compute_all(price, self.currency_id, product=self)
        return included_computed_price["total_excluded"]

    def _get_price_diff_account(self):
        self.ensure_one()
        return False


class ProductProduct(models.Model):
    _inherit = "product.product"

    tax_string = fields.Char(compute="_compute_tax_string")

    def _get_product_accounts(self):
        self.ensure_one()
        return self.product_tmpl_id._get_product_accounts()

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
        """Get the price unit for the product."""
        # Centralised so different models (sale order, account move, etc.)
        # compute the same unit price from the same parameters.
        self.ensure_one()
        company.ensure_one()

        product = self

        if not document_type:
            raise ValueError("document_type is required")

        if product_uom_id is None:
            product_uom_id = product.uom_id
        if not product_currency:
            if document_type == "sale":
                product_currency = product.currency_id
            elif document_type == "purchase":
                product_currency = company.currency_id
        if product_price_unit is None:
            if document_type == "sale":
                product_price_unit = product.with_company(company).lst_price
            elif document_type == "purchase":
                product_price_unit = product.with_company(company).standard_price
            else:
                return 0.0
        if product_taxes is None:
            if document_type == "sale":
                product_taxes = product.taxes_id
            elif document_type == "purchase":
                product_taxes = product.supplier_taxes_id
        if product_taxes:
            product_taxes = product_taxes._filter_taxes_by_company(company)
        # Apply unit of measure.
        if product_uom_id and product.uom_id != product_uom_id:
            product_price_unit = product.uom_id._compute_price(
                product_price_unit, product_uom_id
            )

        # Apply fiscal position.
        if product_taxes and fiscal_position:
            product_price_unit = self._get_tax_included_unit_price_from_price(
                product_price_unit,
                product_taxes,
                fiscal_position=fiscal_position,
            )

        # Apply currency rate. ``product_currency`` is only resolved for the
        # 'sale'/'purchase' document types, so guard against it being unset
        # before dereferencing it (an unknown document_type with an explicit
        # price would otherwise raise AttributeError on ``None``).
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
            record.tax_string = record.product_tmpl_id._construct_tax_string(
                record.lst_price
            )

    # -------------------------------------------------------------------------
    # EDI
    # -------------------------------------------------------------------------

    def _import_retrieve_product_from_barcode(self, product_values):
        barcode = product_values.get("barcode")
        if barcode:
            return {"criteria": [{"domain": [("barcode", "=", barcode)]}]}
        return None

    def _import_retrieve_product_from_default_code(self, product_values):
        default_code = product_values.get("default_code")
        if default_code:
            return {"criteria": [{"domain": [("default_code", "=", default_code)]}]}
        return None

    def _get_product_name_similarity_threshold(self):
        """Similarity ratio in ``(0, 1]`` required to treat two product names as
        a match during import. Falls back to ``0.9`` when the config parameter
        ``account.product_name_similarity_threshold`` is missing, non-numeric, or
        out of range.
        """
        raw = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("account.product_name_similarity_threshold", "0.9")
        )
        try:
            threshold = float(raw)
        except TypeError, ValueError:
            return 0.9
        if not 0.0 < threshold <= 1.0:
            return 0.9
        return threshold

    def _import_retrieve_product_from_name(self, product_values):
        name = product_values.get("name")
        if not name:
            return None

        # Cut the Sales Description from the name (everything after the first line).
        name = name.split("\n", 1)[0]
        if not name:
            return None

        def find_product_by_name_similarity(values):
            """Return the product whose name is most similar to ``name`` when the best ratio meets the configured threshold."""
            # Returning the best match (not the first one over the threshold)
            # avoids auto-linking a weaker candidate that merely sorts earlier.
            similarity_threshold = self._get_product_name_similarity_threshold()
            all_product_ids = self.search(
                Domain.AND(
                    [
                        [("name", "ilike", name)],
                        values["static_domain"],
                    ]
                ),
            ).ids
            lowered_name = name.lower()
            best_product = self.env["product.product"]
            best_ratio = 0.0
            for batch_ids in batched(all_product_ids, PREFETCH_MAX, strict=False):
                products = self.browse(batch_ids)
                products.fetch(["product_tmpl_id"])
                templates = products.product_tmpl_id
                templates.fetch(["name"])
                for product in products:
                    ratio = SequenceMatcher(
                        None, lowered_name, product.name.lower()
                    ).ratio()
                    # ``>`` (not ``>=``) keeps the first candidate on ties.
                    if ratio >= similarity_threshold and ratio > best_ratio:
                        best_ratio = ratio
                        best_product = product
                products.invalidate_recordset()
                templates.invalidate_recordset()
            return best_product

        return {
            "criteria": [
                {"domain": [("name", "=", name)]},
                {
                    "search_method": find_product_by_name_similarity,
                    "cache_key": str([("name", "=", name)]),
                },
            ]
        }

    def _get_import_product_classification_specs(self):
        """Classification-code criteria used to refine product retrieval during import.

        :return: list of dicts with keys ``value_key`` (the ``product_values``
            key), ``field`` (the product field), ``comodel`` (the classification
            model) and ``code_field`` (the field matched on that model).
        :rtype: list[dict]
        """
        # Each spec ties an incoming ``product_values`` key to the model and
        # field that store that classification on the product, so retrieval can
        # both filter and rank on a matching classification. Localization modules
        # override this to contribute their own codes rather than have ``account``
        # name their (possibly not-installed) models.
        return [
            {
                "value_key": "intrastat_code",
                "field": "intrastat_code_id",
                "comodel": "account.intrastat.code",
                "code_field": "code",
            },
            {
                "value_key": "unspsc_code",
                "field": "unspsc_code_id",
                "comodel": "product.unspsc.code",
                "code_field": "code",
            },
            {
                "value_key": "l10n_ro_cpv_code",
                "field": "cpv_code_id",
                "comodel": "l10n_ro.cpv.code",
                "code_field": "code",
            },
            {
                "value_key": "cg_item_classification_code",
                "field": "l10n_hr_kpd_category_id",
                "comodel": "l10n_hr.kpd.category",
                "code_field": "name",
            },
        ]

    def _get_import_product_cache_discriminators(self, product_values):
        """Extra cache-key entries so two rows sharing a search domain but
        differing by classification code are cached separately."""
        return {
            spec["value_key"]: product_values.get(spec["value_key"])
            for spec in self._get_import_product_classification_specs()
        }

    def _get_import_product_classification_domain(self, product_values):
        """Extra domain and ordering that prefer products whose classification
        matches ``product_values``.

        :return: a tuple ``(extra_domain_leaves, order_fields)``.
        """
        extra_domain = []
        order_fields = []
        for spec in self._get_import_product_classification_specs():
            code = product_values.get(spec["value_key"])
            field = spec["field"]
            if not code or field not in self._fields:
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
    def _import_retrieve_product(
        self, search_plan, company, product_values_list, extra_domain=None
    ):
        cache = {}

        static_domain = Domain.OR(
            [
                [*self._check_company_domain(company), ("company_id", "!=", False)],
                [("company_id", "=", False)],
            ]
        )
        if extra_domain:
            static_domain = Domain.AND([static_domain, extra_domain])
        for product_values in product_values_list:
            cache_discriminators = self._get_import_product_cache_discriminators(
                product_values
            )
            # The classification domain/order depend only on product_values, so
            # compute them at most once per row -- and lazily, so a fully cached
            # row pays nothing for the classification-model lookups.
            refined = None

            product = None
            for plan in search_plan:
                plan_values = plan(product_values)
                if not plan_values:
                    continue

                for criteria in plan_values["criteria"]:
                    domain = criteria.get("domain")
                    search_method = criteria.get("search_method")
                    if domain:
                        domain = list(domain)
                        source_cache_key = str(domain)
                    else:
                        source_cache_key = criteria.get("cache_key")

                    cache_key = frozendict(
                        {"cache_key": source_cache_key, **cache_discriminators}
                    )

                    # Reuse a product already found for this key in this run.
                    if cache_key in cache:
                        if product := cache[cache_key]:
                            product_values["product"] = product
                            break
                        continue

                    if refined is None:
                        extra_domain, order_fields = (
                            self._get_import_product_classification_domain(
                                product_values
                            )
                        )
                        refined = (
                            Domain.AND([static_domain, extra_domain]),
                            ", ".join(["company_id", *order_fields, "id DESC"]),
                        )
                    product_domain, order = refined

                    if domain:
                        product = self.search(
                            Domain.AND([product_domain, domain]),
                            order=order,
                            limit=1,
                        )
                    elif search_method:
                        product = search_method(
                            {**criteria, "static_domain": product_domain}
                        )

                    # Only cache a genuine key: a criteria with neither domain nor
                    # cache_key must not poison the cache for another row that
                    # merely shares the same classification codes.
                    if product:
                        if source_cache_key is not None:
                            cache[cache_key] = product
                        product_values["product"] = product
                        break

                if product:
                    break

    def _get_retrieval_product_search_plan(self):
        return [
            (5, self._import_retrieve_product_from_barcode),
            (10, self._import_retrieve_product_from_default_code),
            (15, self._import_retrieve_product_from_name),
        ]

    def _retrieve_product(self, company=None, extra_domain=None, **product_vals):
        """Search all products and find one that matches one of the parameters.

        :param name:            The name of the product.
        :param default_code:    The default_code of the product.
        :param barcode:         The barcode of the product.
        :param company:         The company of the product.
        :param extra_domain:    Any extra domain to add to the search.
        :return:                A product or an empty recordset if not found.
        """
        self._import_retrieve_product(
            search_plan=[
                method
                # Sort on the priority only: the tuples also carry bound methods,
                # which are not orderable, so a bare sort() would crash the moment
                # two plan entries share a priority (e.g. an override colliding
                # with a base one).
                for _priority, method in sorted(
                    self._get_retrieval_product_search_plan(),
                    key=lambda plan: plan[0],
                )
            ],
            company=company or self.env.company,
            product_values_list=[product_vals],
            extra_domain=extra_domain,
        )
        return product_vals.get("product") or self.env["product.product"]

    def _get_price_diff_account(self):
        return self.product_tmpl_id._get_price_diff_account()
