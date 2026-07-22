from collections import defaultdict

from odoo import api, fields, models
from odoo.tools import float_compare


class OrderLineAmountMixin(models.AbstractModel):
    """Line-level amount computation and tax calculation."""

    _name = "order.line.amount.mixin"
    _description = "Order Line Amount Computation"

    # Computes live here (``_compute_amounts``, ``_compute_product_qty``,
    # ``_compute_price_and_discount``); concrete models override the pricing hooks
    # (``_get_auto_price_and_discount``, ``_get_default_product_qty``), extend the
    # ``@api.depends`` sets, and supply their own sale/purchase tax fields.
    # Requires ``order_id``, ``company_id``, ``currency_id``, ``display_type`` and
    # ``price_unit_auto`` from the concrete model or ``order.line.fields.mixin``.

    # ─── Currency (required for Monetary fields) ───────────────────
    # Structural, not composition-defensive: this abstract mixin owns Monetary
    # fields whose ``currency_field`` must resolve on the mixin itself at
    # registry setup. Concrete models also inherit ``currency_id`` from
    # ``order.mixin``, but the mixin must still declare its own. Do not remove.

    currency_id = fields.Many2one("res.currency")

    # ─── Pricing Fields ────────────────────────────────────────────

    product_qty = fields.Float(
        string="Quantity",
        digits="Product Unit",
        compute="_compute_product_qty",
        store=True,
        precompute=True,
        readonly=False,
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
        compute="_compute_price_and_discount",
        store=True,
        precompute=True,
        readonly=False,
        aggregator="avg",
    )
    price_unit_auto = fields.Float(
        string="Automatic Price",
        min_display_digits="Product Price",
        compute="_compute_price_and_discount",
        store=True,
        precompute=True,
        copy=True,
        help="Price from the pricelist/seller. Compared with price_unit to "
        "detect manual overrides.",
    )
    discount = fields.Float(
        string="Discount (%)",
        digits="Discount",
        compute="_compute_price_and_discount",
        store=True,
        precompute=True,
        readonly=False,
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

    @api.depends("product_id", "display_type")
    def _compute_product_qty(self):
        """Set the default quantity when a product is added or changed.

        Subclasses extend the ``@api.depends`` set and override the hooks
        (purchase resets on partner change and defaults to the seller min qty).
        """
        for line in self:
            if line.display_type or not line.product_id:
                line.product_qty = False
                continue
            if not line.product_qty or line._product_qty_reset_triggered():
                line.product_qty = line._get_default_product_qty()

    def _product_qty_reset_triggered(self):
        """Whether the default quantity should be re-applied on change."""
        return bool(
            self._origin.product_id and self._origin.product_id != self.product_id
        )

    def _get_default_product_qty(self):
        """Default quantity for a new/changed line (purchase → seller min qty)."""
        return 1.0

    @api.depends("product_id", "product_id.uom_id", "product_uom_id", "product_qty")
    def _compute_product_uom_qty(self):
        """Convert ``product_qty`` to the product's reference UoM."""
        for line in self:
            if line.display_type:
                line.product_uom_qty = False
            # e.g. 2 Cases where 1 Case = 12 Units → product_qty 2 → product_uom_qty 24
            elif (
                line.product_uom_id
                and line.product_id
                and line.product_id.uom_id != line.product_uom_id
                and line.product_uom_id._has_common_reference(line.product_id.uom_id)
            ):
                line.product_uom_qty = line.product_uom_id._compute_quantity(
                    line.product_qty,
                    line.product_id.uom_id,
                )
            # A vendor/customer may transact in a UoM outside the product's category
            # (e.g. buying a Units product from a vendor quoting in L): no meaningful
            # reference-UoM qty, so fall back to raw rather than raise on incompatible units.
            else:
                line.product_uom_qty = line.product_qty

    def _get_price_unit_gross(self):
        """Return the tax-excluded unit price in the product's reference UoM."""
        self.ensure_one()
        price_unit = self.price_unit
        if self.discount:
            price_unit = price_unit * (1 - self.discount / 100)
        if self.tax_ids:
            qty = self.product_qty or 1
            price_unit = self.tax_ids.compute_all(
                price_unit,
                currency=self.order_id.currency_id,
                quantity=qty,
                rounding_method="round_globally",
            )["total_void"]
            price_unit = price_unit / qty
        if self.product_uom_id.id != self.product_id.uom_id.id:
            price_unit *= self.product_id.uom_id.factor / self.product_uom_id.factor
        return price_unit

    @api.depends("product_id", "product_uom_id", "product_qty", "display_type")
    def _compute_price_and_discount(self):
        """Refresh price/discount from the automatic price unless overridden."""
        force_recompute = self.env.context.get("force_price_recomputation")
        for line in self:
            if line.display_type:
                line.price_unit = False
                line.discount = False
                line.price_unit_auto = False
                continue
            if not line.product_id:
                continue
            # Shadow-price loop: track the auto price in ``price_unit_auto`` and apply
            # it to ``price_unit`` only when not manually overridden. The price source
            # (pricelist vs seller/cost) is model-specific ``_get_auto_price_and_discount``;
            # subclasses extend the ``@api.depends`` trigger set accordingly.
            auto_price, auto_discount = line._get_auto_price_and_discount()
            old_shadow = line.price_unit_auto
            line.price_unit_auto = auto_price
            if line._should_update_price(auto_price, old_shadow, force_recompute):
                line.price_unit = auto_price
                line.discount = auto_discount

    def _get_auto_price_and_discount(self):
        """Return ``(auto_price, auto_discount)`` for this line.

        Sale sources it from the pricelist (with combo / fiscal-position
        handling); purchase from the selected seller or the product cost.
        """
        raise NotImplementedError(
            f"{self._name} must implement _get_auto_price_and_discount()"
        )

    def _should_update_price(
        self, new_auto_price, old_auto_price, force_recompute=False
    ):
        """Whether ``price_unit`` should be refreshed from the automatic price.

        Update when there is no manual override; preserve otherwise.  Subclasses
        gate additional cases via ``_price_update_blocked`` (sale: invoiced /
        expense-cost lines; purchase: invoiced lines / currency changes).

        :param float new_auto_price: newly computed automatic price
        :param float old_auto_price: previous ``price_unit_auto`` (pre-compute)
        :param bool force_recompute: bypass manual-price protection
        :rtype: bool
        """
        self.ensure_one()
        precision = self._get_price_precision()

        if self._price_update_blocked():
            return False

        if force_recompute:
            return True

        # Product changed - always reset to the new product's price.
        if self._origin.product_id and self._origin.product_id != self.product_id:
            return True

        # With a baseline, preserve a price that differs from the old auto price
        # (manual override, including an intentional 0.0 for free products).
        has_baseline = self._origin.id or old_auto_price
        if has_baseline:
            is_manual = (
                float_compare(
                    self.price_unit,
                    old_auto_price,
                    precision_digits=precision,
                )
                != 0
            )
            return not is_manual

        # New line without baseline: keep an explicit non-zero price, else auto.
        return not (
            self.price_unit
            and float_compare(
                self.price_unit,
                new_auto_price,
                precision_digits=precision,
            )
            != 0
        )

    def _price_update_blocked(self):
        """Whether automatic price updates are blocked for this line.

        Sale blocks invoiced and expense-cost lines; purchase blocks invoiced
        lines and currency changes on confirmed orders.
        """
        return False

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
            if line.display_type:
                line.price_unit_discounted_taxinc = False
                continue
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

        Only ever called on lines that already matched on
        ``order.merge.mixin._merge_get_line_key()``, which includes
        ``price_unit``/``tax_ids`` — so both lines are guaranteed to share
        the same price/taxes here; the ``min()`` is a no-op safety net, not
        a real "pick the lower price" policy (t24068: it used to silently
        pick a price and drop taxes for lines that only matched on
        product/UoM/discount but differed in price or tax).
        Called by ``order.merge.mixin._merge_lines()``.
        """
        self.product_qty += source_line.product_qty
        self.price_unit = min(self.price_unit, source_line.price_unit)
