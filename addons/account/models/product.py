import logging
from itertools import batched

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.libs.debug_log import DebugLog
from odoo.libs.text import name_length_band, similarity_ratio
from odoo.models import PREFETCH_MAX
from odoo.tools import SQL

_logger = logging.getLogger(__name__)

_debug = DebugLog(__name__)


DEFAULT_NAME_SIMILARITY_THRESHOLD = 0.9

ACCOUNT_DOMAIN = "[('account_type', 'not in', ('asset_receivable','liability_payable','asset_cash','liability_credit_card','off_balance'))]"


class ProductTemplate(models.Model):
    _name = "product.template"
    _inherit = ["product.template", "mixin.fiscal.country.codes"]

    property_account_income_id = fields.Many2one(
        comodel_name="account.account",
        string="Income Account",
        company_dependent=True,
        domain=ACCOUNT_DOMAIN,
        ondelete="restrict",
        help="Keep this field empty to use the default value from the product category.",
    )
    property_account_expense_id = fields.Many2one(
        comodel_name="account.account",
        string="Expense Account",
        company_dependent=True,
        domain=ACCOUNT_DOMAIN,
        ondelete="restrict",
        help="Keep this field empty to use the default value from the product category. If anglo-saxon accounting with automated valuation method is configured, the expense account on the product category will be used.",
    )
    account_tag_ids = fields.Many2many(
        comodel_name="account.account.tag",
        string="Account Tags",
        domain="[('applicability', '=', 'products')]",
        help="Tags to be set on the base and tax journal items created for this product.",
    )

    def _get_product_accounts(self, fiscal_pos=None):
        self.check_singleton()
        company = self.env.company
        accounts = {
            "income": (
                self.property_account_income_id
                or self._get_category_account("property_account_income_categ_id")
                or company.account_config_id.income_account_id
            ),
            "expense": (
                self.property_account_expense_id
                or self._get_category_account("property_account_expense_categ_id")
                or company.account_config_id.expense_account_id
            ),
        }
        return self._map_product_accounts(accounts, fiscal_pos)

    def _map_product_accounts(self, accounts, fiscal_pos):
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

    @_debug.perf.timed
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
            _debug.logic("uom_change_rejected", templates=self, used_template=row[0])
            raise ValidationError(
                self.env._(
                    "%(product)s is already used on posted journal entries.\n"
                    "To change its Unit of Measure, archive it and create a new product.",
                    product=self.browse(row[0]).display_name,
                )
            )

    @api.model_create_multi
    @_debug.perf.timed
    def create(self, vals_list):
        if _debug.lifecycle.enabled:
            _debug.lifecycle(
                "create",
                model=self._name,
                count=len(vals_list),
                fields=sorted({key for vals in vals_list for key in vals}),
            )
        return super().create(vals_list)

    @_debug.perf.timed
    def write(self, vals):
        _debug.lifecycle("write", records=self, fields=sorted(vals))
        if "uom_id" in vals:
            self.filtered(
                lambda product: product.uom_id.id != vals["uom_id"]
            )._check_uom_not_used_on_a_posted_entry()
        return super().write(vals)


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _get_product_accounts(self, fiscal_pos=None):
        return self.product_tmpl_id._get_product_accounts(fiscal_pos=fiscal_pos)

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

    def _get_domain_name_recall(self, name):
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
            Domain.AND([self._get_domain_name_recall(name), domain])
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
                ratio = similarity_ratio(lowered_name, candidate.lower())
                if ratio >= threshold and ratio > best_ratio:
                    best_ratio = ratio
                    best_product = product
            products.invalidate_recordset()
        _debug.pipeline(
            "name_similarity_matched",
            candidates=len(candidate_ids),
            threshold=threshold,
            best=best_product,
            ratio=best_ratio,
        )
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
        return []

    def _get_classification_record(self, spec, code):
        return self.env[spec["comodel"]].search(
            [(spec["code_field"], "=", code)], limit=1
        )

    def _get_domain_import_product_classification(self, product_values):
        extra_domain = []
        order_fields = []
        for spec in self._get_import_product_classification_specs():
            code = product_values.get(spec["value_key"])
            field = spec["field"]
            if not code:
                continue
            record = self._get_classification_record(spec, code)
            if not record:
                continue
            extra_domain.append((field, "in", (record.id, False)))
            order_fields.append(field)
        return extra_domain, order_fields

    @api.model
    @_debug.perf.timed
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
            self._get_domain_import_product_classification(product_values)
        )
        domain = Domain.AND([domain, classification_domain])
        order = ", ".join(["company_id", *order_fields, "id DESC"])

        for plan in search_plan:
            plan_values = plan(product_values)
            if not plan_values:
                continue
            for criteria in plan_values["criteria"]:
                if criteria_domain := criteria.get("domain"):
                    product = self._get_first_product(
                        Domain.AND([domain, list(criteria_domain)]), order
                    )
                elif search_method := criteria.get("search_method"):
                    product = search_method(domain)
                else:
                    continue
                if product:
                    _debug.logic(
                        "import_product_matched",
                        product=product,
                        criteria=criteria.get("domain") or search_method.__name__,
                    )
                    return product
        _debug.logic("import_no_product_matched", fields=sorted(product_values))
        return self.browse()

    @api.model
    def _get_first_product(self, domain, order):
        return self.search(domain, order=order, limit=1)

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
