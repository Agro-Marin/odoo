from collections import defaultdict

from odoo import api, fields, models
from odoo.tools import float_compare

# ════════════════════════════════════════════════════════════════════
# ORDER-LEVEL AMOUNT MIXIN
# ════════════════════════════════════════════════════════════════════


class OrderAmountMixin(models.AbstractModel):
    """Order-level amount computation and tax totals.

    Consolidates the tax computation pattern that is identical in sale.order
    and purchase.order — both delegate to ``account.tax._get_tax_totals_summary()``
    via a shared helper ``_build_tax_totals_data()``.

    Hook: ``_get_additional_base_lines()`` — returns ``[]`` by default.
    Sale overrides to add early payment discount lines.

    Requires ``order.mixin`` fields: ``currency_id``, ``company_id``,
    ``payment_term_id``, ``currency_rate``.  Requires ``line_ids`` from the
    concrete model.
    """

    _name = "order.amount.mixin"
    _description = "Order Amount Computation"

    # ─── Currency (required for Monetary fields) ───────────────────

    currency_id = fields.Many2one("res.currency")

    # ─── Amount Fields ─────────────────────────────────────────────

    amount_untaxed = fields.Monetary(
        string="Untaxed Amount",
        compute="_compute_amounts",
        store=True,
        tracking=True,
    )
    amount_tax = fields.Monetary(
        string="Taxes",
        compute="_compute_amounts",
        store=True,
        tracking=True,
    )
    amount_total = fields.Monetary(
        string="Total",
        compute="_compute_amounts",
        store=True,
        tracking=True,
    )
    tax_totals = fields.Binary(
        compute="_compute_tax_totals",
        exportable=False,
    )

    # ─── Invoice Amount Fields (order-level sums) ──────────────────

    amount_taxexc_invoiced = fields.Monetary(
        string="Already Invoiced (Tax Excl.)",
        compute="_compute_amounts_invoice",
    )
    amount_taxinc_invoiced = fields.Monetary(
        string="Already Invoiced (Tax Incl.)",
        compute="_compute_amounts_invoice",
    )
    amount_taxexc_to_invoice = fields.Monetary(
        string="Un-invoiced Balance (Tax Excl.)",
        compute="_compute_amounts_invoice",
    )
    amount_taxinc_to_invoice = fields.Monetary(
        string="Un-invoiced Balance (Tax Incl.)",
        compute="_compute_amounts_invoice",
    )

    # ─── Credit Warning ────────────────────────────────────────────

    partner_credit_warning = fields.Text(
        compute="_compute_partner_credit_warning",
    )

    # ─── Tax Computation ───────────────────────────────────────────

    def _build_tax_totals_data(self):
        """Compute the tax totals summary for a single order.

        Shared helper called by both ``_compute_amounts`` (stored monetary
        fields) and ``_compute_tax_totals`` (non-stored display field).

        :return: dict with ``base_amount_currency``, ``tax_amount_currency``,
                 ``total_amount_currency``, and detailed tax breakdown
        :rtype: dict
        """
        self.ensure_one()
        AccountTax = self.env["account.tax"]
        order_lines = self.line_ids.filtered(lambda line: not line.display_type)
        base_lines = [
            line._prepare_base_line_for_taxes_computation() for line in order_lines
        ]
        base_lines += self._get_additional_base_lines()
        AccountTax._add_tax_details_in_base_lines(base_lines, self.company_id)
        AccountTax._round_base_lines_tax_details(base_lines, self.company_id)
        return AccountTax._get_tax_totals_summary(
            base_lines=base_lines,
            currency=self.currency_id or self.company_id.currency_id,
            company=self.company_id,
        )

    def _get_additional_base_lines(self):
        """Hook for additional base lines in tax computation.

        Sale overrides to add early payment discount lines.

        :return: list of base line dicts for tax computation
        :rtype: list
        """
        return []

    @api.depends_context("lang")
    @api.depends(
        "company_id",
        "currency_id",
        "payment_term_id",
        "line_ids.price_subtotal",
    )
    def _compute_amounts(self):
        """Compute stored amount fields from tax totals."""
        for order in self:
            tax_totals = order._build_tax_totals_data()
            order.amount_untaxed = tax_totals["base_amount_currency"]
            order.amount_tax = tax_totals["tax_amount_currency"]
            order.amount_total = tax_totals["total_amount_currency"]

    @api.depends_context("lang")
    @api.depends(
        "company_id",
        "currency_id",
        "payment_term_id",
        "line_ids.price_subtotal",
    )
    def _compute_tax_totals(self):
        """Compute the non-stored ``tax_totals`` display field.

        Separated from ``_compute_amounts`` to avoid inconsistent store
        attribute warnings (Binary, not stored).
        """
        for order in self:
            order.tax_totals = order._build_tax_totals_data()

    # ─── Invoice Amounts ───────────────────────────────────────────

    @api.depends(
        "line_ids.amount_taxexc_invoiced",
        "line_ids.amount_taxexc_to_invoice",
        "line_ids.amount_taxinc_invoiced",
        "line_ids.amount_taxinc_to_invoice",
    )
    def _compute_amounts_invoice(self):
        """Compute order-level invoice amounts as the sum of line amounts.

        Single-pass iteration — identical in sale.order and purchase.order.
        """
        for order in self:
            taxexc_invoiced = 0.0
            taxexc_to_invoice = 0.0
            taxinc_invoiced = 0.0
            taxinc_to_invoice = 0.0

            for line in order.line_ids:
                taxexc_invoiced += line.amount_taxexc_invoiced
                taxexc_to_invoice += line.amount_taxexc_to_invoice
                taxinc_invoiced += line.amount_taxinc_invoiced
                taxinc_to_invoice += line.amount_taxinc_to_invoice

            order.amount_taxexc_invoiced = taxexc_invoiced
            order.amount_taxexc_to_invoice = taxexc_to_invoice
            order.amount_taxinc_invoiced = taxinc_invoiced
            order.amount_taxinc_to_invoice = taxinc_to_invoice

    # ─── Credit Warning ────────────────────────────────────────────

    @api.depends("company_id", "partner_id", "amount_total")
    def _compute_partner_credit_warning(self):
        """Warn about the partner credit limit on draft orders."""
        for order in self:
            order = order.with_company(order.company_id)
            order.partner_credit_warning = ""
            show_warning = (
                order.state == "draft" and order.company_id.account_use_credit_limit
            )
            if show_warning:
                order.partner_credit_warning = self.env[
                    "account.move"
                ]._build_credit_warning_message(
                    order.sudo(),  # ensure access to `credit` & `credit_limit` fields
                    current_amount=(order.amount_total / order.currency_rate),
                )


# ════════════════════════════════════════════════════════════════════
# LINE-LEVEL AMOUNT MIXIN
# ════════════════════════════════════════════════════════════════════


class OrderLineAmountMixin(models.AbstractModel):
    """Line-level amount computation and tax calculation.

    Provides:
    - Standard pricing fields (``product_qty``, ``price_unit``, ``discount``,
      ``tax_ids``)
    - Batched tax computation (``_compute_amounts``, grouped by company)
    - UoM quantity conversion (``product_uom_qty``)
    - Base line preparation for the tax engine

    Pricing fields are defined **without** compute — each concrete model
    provides its own (pricelist vs supplier info, sale vs purchase taxes).

    Requires ``order_id``, ``company_id``, ``currency_id``, ``display_type``,
    ``price_unit_auto`` from the concrete model or ``order.line.fields.mixin``.
    """

    _name = "order.line.amount.mixin"
    _description = "Order Line Amount Computation"

    # ─── Currency (required for Monetary fields) ───────────────────

    currency_id = fields.Many2one("res.currency")

    # ─── Pricing Fields (compute provided by concrete models) ──────

    product_qty = fields.Float(
        string="Quantity",
        digits="Product Unit",
    )
    product_uom_qty = fields.Float(
        string="Quantity (Reference UoM)",
        digits="Product Unit",
        compute="_compute_product_uom_qty",
        store=True,
        precompute=True,
    )
    price_unit = fields.Float(
        string="Unit Price",
        min_display_digits="Product Price",
    )
    discount = fields.Float(
        string="Discount (%)",
        digits="Discount",
    )
    tax_ids = fields.Many2many(
        comodel_name="account.tax",
        string="Taxes",
        check_company=True,
        context={"active_test": False, "hide_original_tax_ids": True},
    )

    # ─── Computed Amount Fields ────────────────────────────────────

    price_subtotal = fields.Monetary(
        string="Subtotal",
        compute="_compute_amounts",
        store=True,
        precompute=True,
    )
    price_tax = fields.Monetary(
        string="Total Tax",
        compute="_compute_amounts",
        store=True,
        precompute=True,
    )
    price_total = fields.Monetary(
        string="Total",
        compute="_compute_amounts",
        store=True,
        precompute=True,
    )

    # ─── Compute Methods ───────────────────────────────────────────

    @api.depends("tax_ids", "product_qty", "price_unit", "discount")
    def _compute_amounts(self):
        """Compute line amounts with taxes, batched by company.

        Display lines (sections/notes) get False amounts; product lines are
        grouped by company for batch tax computation instead of per-line calls.
        """
        AccountTax = self.env["account.tax"]
        lines = self.env[self._name]
        for line in self:
            if line.display_type:
                line.price_subtotal = False
                line.price_total = False
                line.price_tax = False
            else:
                lines += line
        if not lines:
            return

        base_lines_by_company = defaultdict(list)
        line_to_base = {}
        for line in lines:
            base_line = line._prepare_base_line_for_taxes_computation()
            company = line.company_id or self.env.company
            base_lines_by_company[company].append(base_line)
            line_to_base[line.id] = base_line

        for company, base_lines in base_lines_by_company.items():
            AccountTax._add_tax_details_in_base_lines(base_lines, company)
            AccountTax._round_base_lines_tax_details(base_lines, company)

        for line in lines:
            base_line = line_to_base[line.id]
            line.price_subtotal = base_line["tax_details"]["total_excluded_currency"]
            line.price_total = base_line["tax_details"]["total_included_currency"]
            line.price_tax = line.price_total - line.price_subtotal

    @api.depends("product_id", "product_id.uom_id", "product_uom_id", "product_qty")
    def _compute_product_uom_qty(self):
        """Convert ``product_qty`` to the product's reference UoM.

        Example: 2 Cases where 1 Case = 12 Units →
        ``product_qty = 2`` (Cases), ``product_uom_qty = 24`` (Units).
        """
        for line in self:
            if line.display_type:
                line.product_uom_qty = False
                continue
            if not line.product_uom_id or not line.product_id:
                line.product_uom_qty = line.product_qty
            elif line.product_id.uom_id != line.product_uom_id:
                line.product_uom_qty = line.product_uom_id._compute_quantity(
                    line.product_qty,
                    line.product_id.uom_id,
                )
            else:
                line.product_uom_qty = line.product_qty

    def _get_base_line_special_type(self):
        """Return the tax-engine special type for this line, if any.

        Sale overrides to return ``'global_discount'`` for discount lines.

        :rtype: str | False
        """
        self.ensure_one()
        return "down_payment" if self.is_downpayment else False

    def _prepare_base_line_for_taxes_computation(self, **kwargs):
        """Prepare a base line dict for the ``account.tax`` computation engine.

        :return: dict suitable for ``account.tax._add_tax_details_in_base_lines()``
        :rtype: dict
        """
        self.ensure_one()
        company = self.order_id.company_id or self.env.company
        base_values = {
            "tax_ids": self.tax_ids,
            "quantity": self.product_qty,
            "partner_id": self.order_id.partner_id,
            "currency_id": self.order_id.currency_id or company.currency_id,
            "rate": self.order_id.currency_rate,
            "name": self.name,
        }
        special_type = self._get_base_line_special_type()
        if special_type:
            base_values["special_type"] = special_type
        base_values.update(kwargs)
        return self.env["account.tax"]._prepare_base_line_for_taxes_computation(
            self,
            **base_values,
        )

    # ─── Discounted Price Fields ────────────────────────────────────

    price_unit_discounted_taxexc = fields.Float(
        string="Unit Price Discounted Tax Excluded",
        min_display_digits="Product Price",
        compute="_compute_price_unit_discounted_taxexc",
    )
    price_unit_discounted_taxinc = fields.Float(
        string="Unit Price Discounted Tax Included",
        min_display_digits="Product Price",
        compute="_compute_price_unit_discounted_taxinc",
    )

    @api.depends("price_unit", "discount")
    def _compute_price_unit_discounted_taxexc(self):
        for line in self:
            if line.display_type:
                line.price_unit_discounted_taxexc = False
                continue
            line.price_unit_discounted_taxexc = line.price_unit * (
                1 - (line.discount or 0.0) / 100.0
            )

    @api.depends("product_qty", "price_total")
    def _compute_price_unit_discounted_taxinc(self):
        for line in self:
            line.price_unit_discounted_taxinc = (
                line.price_total / line.product_qty if line.product_qty else 0.0
            )

    # ─── Tax Computation ────────────────────────────────────────────

    def _get_product_tax_field(self):
        """Return the product field name holding taxes for this order type.

        Sale: ``'taxes_id'`` (customer taxes).
        Purchase: ``'supplier_taxes_id'`` (vendor taxes).
        """
        if self._get_order_type() == "sale":
            return "taxes_id"
        return "supplier_taxes_id"

    def _get_custom_compute_tax_cache_key(self):
        """Hook to extend the tax cache key with model-specific values."""
        return ()

    @api.depends("company_id", "product_id")
    def _compute_tax_ids(self):
        """Compute taxes from the product, filtered by company and fiscal position.

        Groups lines by company for batch ``with_company`` scoping.
        Uses a cache keyed on ``(fiscal_position, company, tax_ids)``
        to avoid redundant ``map_tax`` calls.

        Purchase extends the dependencies with ``fiscal_position_id``
        (auto-recompute); sale deliberately recomputes taxes only on demand.
        """
        lines_by_company = defaultdict(lambda: self.env[self._name])
        cached_taxes = {}
        tax_field = self._get_product_tax_field()
        for line in self.filtered(lambda l: not l.display_type):
            if not line.product_id or not line._tax_ids_include_product(line):
                line.tax_ids = False
                continue
            lines_by_company[line.company_id] += line

        for company, lines in lines_by_company.items():
            for line in lines.with_company(company):
                taxes = line.product_id[tax_field]._filter_taxes_by_company(
                    company,
                )
                if not taxes:
                    line.tax_ids = False
                    continue
                fiscal_position = line.order_id.fiscal_position_id
                cache_key = (fiscal_position.id, company.id, tuple(taxes.ids))
                cache_key += line._get_custom_compute_tax_cache_key()
                if cache_key in cached_taxes:
                    result = cached_taxes[cache_key]
                else:
                    result = fiscal_position.map_tax(taxes)
                    cached_taxes[cache_key] = result
                line.tax_ids = result

    def _tax_ids_include_product(self, line):
        """Whether this product should have taxes computed.

        Sale overrides to exclude combo products.
        """
        return True

    # ─── Analytic Distribution ──────────────────────────────────────

    @api.depends("company_id", "partner_id", "product_id")
    def _compute_analytic_distribution(self):
        """Compute analytic distribution with cross-record caching."""
        cache = {}
        AnalyticModel = self.env["account.analytic.distribution.model"]

        for line in self.filtered(lambda l: not l.display_type):
            partner = line.order_id.partner_id
            partner_category_ids = tuple(partner.category_id.ids)
            cache_key = (
                line.product_id.id,
                line.product_categ_id.id,
                partner.id,
                partner_category_ids,
                line.company_id.id,
            )
            if cache_key not in cache:
                cache[cache_key] = AnalyticModel._get_distribution(
                    {
                        "product_id": line.product_id.id,
                        "product_categ_id": line.product_categ_id.id,
                        "partner_id": partner.id,
                        "partner_category_id": list(partner_category_ids),
                        "company_id": line.company_id.id,
                    },
                )
            distribution = cache[cache_key]
            line.analytic_distribution = distribution or line.analytic_distribution

    # ─── Manual Price Detection ─────────────────────────────────────

    def _get_price_precision(self):
        """Return decimal precision for price comparisons.

        Purchase overrides to include currency decimal places.
        """
        return self.env["decimal.precision"].precision_get("Product Price")

    def is_manual_price(self):
        """Check if the current price is a manual override (not auto-priced).

        :return: True if ``price_unit`` differs from ``price_unit_auto``
        :rtype: bool
        """
        self.ensure_one()
        if not self.price_unit_auto:
            return False
        precision = self._get_price_precision()
        return (
            float_compare(
                self.price_unit,
                self.price_unit_auto,
                precision_digits=precision,
            )
            != 0
        )

    # ─── Merge Support ─────────────────────────────────────────────

    def _merge_order_line(self, source_line):
        """Merge a source line into this line by combining quantities.

        Takes the best (lowest) price between the two lines.
        Called by ``order.merge.mixin._merge_lines()``.
        """
        self.product_qty += source_line.product_qty
        self.price_unit = min(self.price_unit, source_line.price_unit)
