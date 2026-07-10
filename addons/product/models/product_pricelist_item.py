from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_round, format_amount, format_datetime, formatLang


class ProductPricelistItem(models.Model):
    _name = "product.pricelist.item"
    _description = "Pricelist Rule"
    _order = "applied_on, min_quantity desc, categ_id desc, id desc"
    _check_company_auto = True

    pricelist_id = fields.Many2one(
        comodel_name="product.pricelist",
        string="Pricelist",
        required=False,
        default=lambda self: self._default_pricelist_id(),
        ondelete="cascade",
        # Standard flows do not handle rules without pricelists (but some custom modules do)!
        index=True,
    )

    is_pricelist_required = fields.Boolean(compute="_compute_is_pricelist_required")

    company_id = fields.Many2one(
        comodel_name="res.company",
        compute="_compute_company_id",
        store=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        compute="_compute_currency_id",
        store=True,
    )

    date_start = fields.Datetime(
        string="Start Date",
        help="Starting datetime for the pricelist item validation\n"
        "The displayed value depends on the timezone set in your preferences.",
    )
    date_end = fields.Datetime(
        string="End Date",
        help="Ending datetime for the pricelist item validation\n"
        "The displayed value depends on the timezone set in your preferences.",
    )

    min_quantity = fields.Float(
        string="Min. Quantity",
        digits="Product Unit",
        default=0,
        help="For the rule to apply, bought/sold quantity must be greater "
        "than or equal to the minimum quantity specified in this field.\n"
        "Expressed in the default unit of measure of the product.",
    )

    applied_on = fields.Selection(
        selection=[
            ("3_global", "All Products"),
            ("2_product_category", "Product Category"),
            ("1_product", "Product"),
            ("0_product_variant", "Product Variant"),
        ],
        string="Apply On",
        required=True,
        default="3_global",
        help="Pricelist Item applicable on selected option",
    )

    display_applied_on = fields.Selection(
        selection=[
            ("1_product", "Product"),
            ("2_product_category", "Category"),
        ],
        required=True,
        default="1_product",
        help="Pricelist Item applicable on selected option",
    )

    categ_id = fields.Many2one(
        comodel_name="product.category",
        string="Category",
        ondelete="cascade",
        help="Specify a product category if this rule only applies to products belonging to this category or its children categories. Keep empty otherwise.",
    )
    product_tmpl_id = fields.Many2one(
        comodel_name="product.template",
        string="Product",
        check_company=True,
        ondelete="cascade",
        index="btree_not_null",
        help="Specify a template if this rule only applies to one product template. Keep empty otherwise.",
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Variant",
        check_company=True,
        domain="[('product_tmpl_id', '=', product_tmpl_id)]",
        ondelete="cascade",
        index="btree_not_null",
        help="Specify a product if this rule only applies to one product. Keep empty otherwise.",
    )
    product_uom_name = fields.Char(
        related="product_tmpl_id.uom_name",
    )
    product_variant_count = fields.Integer(
        related="product_tmpl_id.product_variant_count",
    )

    base = fields.Selection(
        selection=[
            ("list_price", "Sales Price"),
            ("standard_price", "Cost"),
            ("pricelist", "Other Pricelist"),
        ],
        string="Based on",
        required=True,
        default="list_price",
        help="Base price for computation.\n"
        "Sales Price: The base price will be the Sales Price.\n"
        "Cost Price: The base price will be the cost price.\n"
        "Other Pricelist: Computation of the base price based on another Pricelist.",
    )
    base_pricelist_id = fields.Many2one(
        comodel_name="product.pricelist",
        string="Other Pricelist",
        check_company=True,
    )

    compute_price = fields.Selection(
        selection=[
            ("percentage", "Discount"),
            ("formula", "Formula"),
            ("fixed", "Fixed Price"),
        ],
        required=True,
        default="fixed",
        index=True,
        help="Use the discount rules and activate the discount settings in order to show discount to customer.",
    )

    fixed_price = fields.Float(
        string="Fixed Price",
        min_display_digits="Product Price",
    )
    percent_price = fields.Float(
        string="Percentage Price",
        help="You can apply a mark-up by setting a negative discount.",
    )

    price_discount = fields.Float(
        string="Price Discount",
        digits=(16, 2),
        default=0,
        help="You can apply a mark-up by setting a negative discount.",
    )
    price_round = fields.Float(
        string="Price Rounding",
        min_display_digits="Product Price",
        help="Sets the price so that it is a multiple of this value.\n"
        "Rounding is applied after the discount and before the surcharge.\n"
        "To have prices that end in 9.99, round off to 10.00 and set an extra at -0.01",
    )
    price_surcharge = fields.Float(
        string="Extra Fee",
        min_display_digits="Product Price",
        help="Specify the fixed amount to add or subtract (if negative) to the amount calculated with the discount.",
    )

    price_markup = fields.Float(
        string="Markup",
        digits=(16, 2),
        compute="_compute_price_markup",
        inverse="_inverse_price_markup",
        help="You can apply a mark-up on the cost",
        # Not stored: it is purely the negation of price_discount (see
        # _compute_price_markup). The inverse persists edits onto price_discount.
    )

    price_min_margin = fields.Float(
        string="Min. Price Margin",
        min_display_digits="Product Price",
        help="Specify the minimum amount of margin over the base price.",
    )
    price_max_margin = fields.Float(
        string="Max. Price Margin",
        min_display_digits="Product Price",
        help="Specify the maximum amount of margin over the base price.",
    )

    # functional fields used for usability purposes
    name = fields.Char(
        string="Name",
        compute="_compute_name",
        help="Explicit rule name for this pricelist line.",
    )
    price = fields.Char(
        string="Price",
        compute="_compute_price_label",
        help="Human-readable summary of the price this rule computes.",
    )
    rule_tip = fields.Char(
        compute="_compute_rule_tip",
    )

    # === CONSTRAINT METHODS ===#

    @api.constrains("base_pricelist_id", "pricelist_id", "base")
    def _check_pricelist_recursion(self):
        def dfs_path(from_pl, to_pl, path, seen):
            if (from_pl, to_pl) in seen:
                # If another pricelist rule from the same pricelist has the same
                # target, there is no need to test that path again.
                return path.browse()
            if to_pl in path:
                return path + to_pl
            seen.add((from_pl, to_pl))
            target_pricelists = self.env["product.pricelist.item"]._read_group(
                domain=[("pricelist_id", "=", to_pl.id), ("base", "=", "pricelist")],
                groupby=["base_pricelist_id"],
            )
            new_path = path + to_pl
            for (pricelist,) in target_pricelists:
                if pricelist and (res := dfs_path(to_pl, pricelist, new_path, seen)):
                    return res
            return path.browse()

        seen = set()
        for item in self:
            # Skip validation for rules not based on other pricelists.
            if (
                item.base != "pricelist"
                or not item.base_pricelist_id
                or not item.pricelist_id
            ):
                continue
            if path := dfs_path(
                item.pricelist_id, item.base_pricelist_id, item.pricelist_id, seen
            ):
                raise ValidationError(
                    _(
                        "Recursive pricelist rules detected: %s",
                        " ⇒ ".join(path.mapped("name")),
                    ),
                )

    @api.constrains("date_start", "date_end")
    def _check_date_range(self):
        for item in self:
            if item.date_start and item.date_end and item.date_start >= item.date_end:
                raise ValidationError(
                    _(
                        "%(item_name)s: end date (%(end_date)s) should be after start date (%(start_date)s)",
                        item_name=item.display_name,
                        end_date=format_datetime(self.env, item.date_end),
                        start_date=format_datetime(self.env, item.date_start),
                    ),
                )

    @api.constrains("price_min_margin", "price_max_margin")
    def _check_margin(self):
        for item in self:
            # A zero max margin means "no upper cap" in _compute_price, so it is
            # only a real bound (and thus comparable to the min) when non-zero.
            if item.price_max_margin and item.price_min_margin > item.price_max_margin:
                raise ValidationError(
                    _(
                        "%(rule)s: the minimum margin (%(min)s) must be lower than"
                        " the maximum margin (%(max)s).",
                        rule=item.display_name,
                        min=item.price_min_margin,
                        max=item.price_max_margin,
                    ),
                )

    @api.constrains("product_id", "product_tmpl_id", "categ_id")
    def _check_product_consistency(self):
        for item in self:
            if item.applied_on == "2_product_category" and not item.categ_id:
                raise ValidationError(
                    _(
                        "Please specify the category for which this rule should be applied"
                    ),
                )
            if item.applied_on == "1_product" and not item.product_tmpl_id:
                raise ValidationError(
                    _(
                        "Please specify the product for which this rule should be applied"
                    ),
                )
            if item.applied_on == "0_product_variant" and not item.product_id:
                raise ValidationError(
                    _(
                        "Please specify the product variant for which this rule should be applied"
                    ),
                )

    @api.constrains("base_pricelist_id", "base")
    def _check_base_pricelist_id(self):
        if any(
            item.base == "pricelist" and not item.base_pricelist_id for item in self
        ):
            raise ValidationError(
                _(
                    'A pricelist item with "Other Pricelist" as base must have a base_pricelist_id.'
                ),
            )

    @api.constrains("price_round")
    def _check_price_round(self):
        for item in self:
            # float_round() raises on a negative precision, so a bad value stored
            # via import/RPC would crash every price computation for this rule.
            if item.price_round and item.price_round < 0:
                raise ValidationError(
                    _(
                        "%(rule)s: the price rounding must be strictly positive.",
                        rule=item.display_name,
                    ),
                )

    # === CRUD METHODS ===#

    @api.model_create_multi
    def create(self, vals_list):
        # Batch-resolve the template of variant-only vals in a single read rather
        # than one browse per row - an N+1 that bites bulk imports/RPC, where the
        # referenced variants are typically not yet in cache.
        missing_tmpl_ids = [
            vals["product_id"]
            for vals in vals_list
            if vals.get("product_id") and not vals.get("product_tmpl_id")
        ]
        tmpl_by_variant = {
            variant.id: variant.product_tmpl_id.id
            for variant in self.env["product.product"].browse(missing_tmpl_ids)
        }

        for values in vals_list:
            if values.get("product_id") and not values.get("product_tmpl_id"):
                # Deduce the template from the variant so the rule stays properly
                # configured/displayed even with partial data (mostly for imports).
                values["product_tmpl_id"] = tmpl_by_variant.get(values["product_id"])

            if not values.get("applied_on"):
                values["applied_on"] = self._deduce_applied_on(
                    product_id=values.get("product_id"),
                    product_tmpl_id=values.get("product_tmpl_id"),
                    categ_id=values.get("categ_id"),
                )

            # Ensure item consistency for later searches.
            self._sanitize_applied_on_vals(values)
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("applied_on"):
            # Ensure item consistency for later searches.
            self._sanitize_applied_on_vals(vals)
        return super().write(vals)

    @api.model
    def _deduce_applied_on(
        self, product_id=False, product_tmpl_id=False, categ_id=False
    ):
        """Return the ``applied_on`` level implied by the targeting fields.

        Precedence: variant > template > category > global. Single source of
        truth for deducing the level, shared by ``create`` and the onchanges.
        """
        if product_id:
            return "0_product_variant"
        if product_tmpl_id:
            return "1_product"
        if categ_id:
            return "2_product_category"
        return "3_global"

    @api.model
    def _sanitize_applied_on_vals(self, vals):
        """Null out the product/category links that don't match ``applied_on``.

        Keeps a rule's targeting fields consistent with its ``applied_on`` level
        so later rule searches (``_get_applicable_rules_domain``) stay reliable.
        Mutates ``vals`` in place; no-op when ``applied_on`` is absent/unknown.
        """
        applied_on = vals.get("applied_on")
        if applied_on == "3_global":
            vals.update({"product_id": None, "product_tmpl_id": None, "categ_id": None})
        elif applied_on == "2_product_category":
            vals.update({"product_id": None, "product_tmpl_id": None})
        elif applied_on == "1_product":
            vals.update({"product_id": None, "categ_id": None})
        elif applied_on == "0_product_variant":
            vals.update({"categ_id": None})

    # === COMPUTE METHODS ===#

    def _compute_is_pricelist_required(self):
        # Override hook: some flows (e.g. sale_subscription plans) set this to
        # False; views bind `required="is_pricelist_required"` on pricelist_id.
        self.is_pricelist_required = True

    @api.depends("pricelist_id.company_id", "product_tmpl_id")
    def _compute_company_id(self):
        for item in self:
            item.company_id = (
                item.pricelist_id.company_id or item.product_tmpl_id.company_id
            )

    @api.depends("pricelist_id.currency_id", "company_id")
    def _compute_currency_id(self):
        for item in self:
            item.currency_id = (
                item.pricelist_id.currency_id
                or item.company_id.currency_id
                or item.env.company.currency_id
            )

    @api.depends(
        "applied_on", "categ_id", "product_tmpl_id", "product_id", "display_applied_on"
    )
    def _compute_name(self):
        for item in self:
            if item.categ_id and item.applied_on == "2_product_category":
                item.name = _("Category: %s", item.categ_id.display_name)
            elif item.product_tmpl_id and item.applied_on == "1_product":
                item.name = item.product_tmpl_id.display_name
            elif item.product_id and item.applied_on == "0_product_variant":
                item.name = _("Variant: %s", item.product_id.display_name)
            elif item.display_applied_on == "2_product_category":
                item.name = _("All Categories")
            else:
                item.name = _("All Products")

    @api.depends(
        "compute_price",
        "fixed_price",
        "pricelist_id",
        "percent_price",
        "price_discount",
        "price_markup",
        "price_surcharge",
        "base",
        "base_pricelist_id",
        "currency_id",
    )
    def _compute_price_label(self):
        for item in self:
            if item.compute_price == "fixed":
                item.price = formatLang(
                    item.env,
                    item.fixed_price,
                    dp="Product Price",
                    currency_obj=item.currency_id,
                )
            elif item.compute_price == "percentage":
                percentage = self._int_if_whole(item.percent_price)
                if item.base_pricelist_id:
                    item.price = _(
                        "%(percentage)s %% discount on %(pricelist)s",
                        percentage=percentage,
                        pricelist=item.base_pricelist_id.display_name,
                    )
                else:
                    item.price = _(
                        "%(percentage)s %% discount on sales price",
                        percentage=percentage,
                    )
            else:
                base_str = item._get_price_label_base_str()

                extra_fee_str = ""
                if item.price_surcharge > 0:
                    extra_fee_str = _(
                        "+ %(amount)s extra fee",
                        amount=format_amount(
                            item.env,
                            abs(item.price_surcharge),
                            currency=item.currency_id,
                        ),
                    )
                elif item.price_surcharge < 0:
                    extra_fee_str = _(
                        "- %(amount)s rebate",
                        amount=format_amount(
                            item.env,
                            abs(item.price_surcharge),
                            currency=item.currency_id,
                        ),
                    )
                discount_type, percentage = item._get_displayed_discount()
                item.price = _(
                    "%(percentage)s %% %(discount_type)s on %(base)s %(extra)s",
                    percentage=percentage,
                    discount_type=discount_type,
                    base=base_str,
                    extra=extra_fee_str,
                )

    @api.depends("price_discount")
    def _compute_price_markup(self):
        for item in self:
            item.price_markup = -item.price_discount

    def _inverse_price_markup(self):
        for item in self:
            item.price_discount = -item.price_markup

    @api.depends_context("lang")
    @api.depends(
        "base",
        "compute_price",
        "price_discount",
        "price_markup",
        "price_round",
        "price_surcharge",
        "currency_id",
    )
    def _compute_rule_tip(self):
        base_selection_vals = dict(
            self._fields["base"]._description_selection(self.env)
        )
        self.rule_tip = False
        for item in self:
            if item.compute_price != "formula" or not item.base:
                continue
            base_amount = 100
            # price_markup is -price_discount, so both are equal here.
            discount = item.price_discount
            discount_factor = (100 - discount) / 100
            discounted_price = base_amount * discount_factor
            if item.price_round:
                discounted_price = float_round(
                    discounted_price, precision_rounding=item.price_round
                )
            surcharge = format_amount(item.env, item.price_surcharge, item.currency_id)
            discount_type, discount = item._get_displayed_discount()

            item.rule_tip = _(
                "%(base)s with a %(discount)s %% %(discount_type)s and %(surcharge)s extra fee\n"
                "Example: %(amount)s * %(discount_charge)s + %(price_surcharge)s → %(total_amount)s",
                base=base_selection_vals[item.base],
                discount=discount,
                discount_type=discount_type,
                surcharge=surcharge,
                amount=format_amount(item.env, 100, item.currency_id),
                discount_charge=discount_factor,
                price_surcharge=surcharge,
                total_amount=format_amount(
                    item.env, discounted_price + item.price_surcharge, item.currency_id
                ),
            )

    def _get_displayed_discount(self):
        self.ensure_one()
        if self.base == "standard_price":
            return _("markup"), self._int_if_whole(self.price_markup)
        return _("discount"), self._int_if_whole(self.price_discount)

    def _int_if_whole(self, percentage):
        """Return ``percentage`` as an int when it has no fractional part.

        Used for display so a whole percentage shows as ``25`` rather than
        ``25.0``; a fractional one keeps its decimals.
        """
        return int(percentage) if percentage == int(percentage) else percentage

    def _get_price_label_base_str(self):
        """This method allows you to extend it to other modules with other
        options in the base field to return a different text.
        """
        self.ensure_one()
        base_str = ""
        if self.base == "pricelist" and self.base_pricelist_id:
            base_str = self.base_pricelist_id.display_name
        elif self.base == "standard_price":
            base_str = _("product cost")
        else:
            base_str = _("sales price")
        return base_str

    def _default_pricelist_id(self):
        return self.env["product.pricelist"].search(
            ["|", ("company_id", "=", False), ("company_id", "=", self.env.company.id)],
            limit=1,
        )

    # === ONCHANGE METHODS ===#

    @api.onchange("base")
    def _onchange_base(self):
        for item in self:
            item.update(
                {
                    "price_discount": 0.0,
                    "price_markup": 0.0,
                }
            )

    @api.onchange("base_pricelist_id")
    def _onchange_base_pricelist_id(self):
        for item in self:
            if item.compute_price == "percentage":
                item.base = (
                    bool(item.base_pricelist_id) and "pricelist"
                ) or "list_price"

    @api.onchange("compute_price")
    def _onchange_compute_price(self):
        self.base_pricelist_id = False
        if self.compute_price != "fixed":
            self.fixed_price = 0.0
        if self.compute_price != "percentage":
            self.percent_price = 0.0
        if self.compute_price != "formula":
            self.update(
                {
                    "base": "list_price",
                    "price_discount": 0.0,
                    "price_surcharge": 0.0,
                    "price_markup": 0.0,
                    "price_round": 0.0,
                    "price_min_margin": 0.0,
                    "price_max_margin": 0.0,
                }
            )

    @api.onchange("display_applied_on")
    def _onchange_display_applied_on(self):
        for item in self:
            if not (item.product_tmpl_id or item.categ_id):
                item.update({"applied_on": "3_global"})
            elif item.display_applied_on == "1_product":
                item.update(
                    {
                        "applied_on": "1_product",
                        "categ_id": None,
                    }
                )
            elif item.display_applied_on == "2_product_category":
                item.update(
                    {
                        "product_id": None,
                        "product_tmpl_id": None,
                        "applied_on": "2_product_category",
                        "product_uom_name": None,
                    }
                )

    @api.onchange("product_id")
    def _onchange_product_id(self):
        has_product_id = self.filtered("product_id")
        for item in has_product_id:
            item.product_tmpl_id = item.product_id.product_tmpl_id
        if self.env.context.get("default_applied_on", False) == "1_product":
            # If a product variant is specified, apply on variants instead
            # Reset if product variant is removed
            has_product_id.update({"applied_on": "0_product_variant"})
            (self - has_product_id).update({"applied_on": "1_product"})

    @api.onchange("product_tmpl_id")
    def _onchange_product_tmpl_id(self):
        has_tmpl_id = self.filtered("product_tmpl_id")
        for item in has_tmpl_id:
            if (
                item.product_id
                and item.product_id.product_tmpl_id != item.product_tmpl_id
            ):
                item.product_id = None

    @api.onchange("product_id", "product_tmpl_id", "categ_id")
    def _onchange_rule_content(self):
        if not self.env.context.get("default_applied_on", False):
            # If we aren't coming from a specific product template/variant.
            variants_rules = self.filtered(
                lambda r: bool(r.product_id) and bool(r.product_tmpl_id)
            )
            template_rules = (self - variants_rules).filtered("product_tmpl_id")
            category_rules = self.filtered("categ_id")
            variants_rules.update({"applied_on": "0_product_variant"})
            template_rules.update({"applied_on": "1_product"})
            category_rules.update({"applied_on": "2_product_category"})
            global_rules = self - variants_rules - template_rules - category_rules
            global_rules.update({"applied_on": "3_global"})

    @api.onchange("price_round")
    def _onchange_price_round(self):
        self._check_price_round()

    @api.onchange("date_start", "date_end")
    def _onchange_validity_period(self):
        self._check_date_range()

    # === BUSINESS METHODS ===#

    def _is_applicable_for(self, product, qty_in_product_uom):
        """Check whether the current rule is valid for the given product & qty.

        Note: self.ensure_one()

        :param product: product record (product.product/product.template)
        :param float qty_in_product_uom: quantity, expressed in product UoM
        :returns: Whether rules is valid or not
        :rtype: bool
        """
        self.ensure_one()
        product.ensure_one()

        if self.min_quantity and qty_in_product_uom < self.min_quantity:
            return False

        if self.applied_on == "2_product_category":
            if not product.categ_id:
                return False
            # Applicable on the rule's category or any of its descendants.
            return (
                product.categ_id == self.categ_id
                or product.categ_id.parent_path.startswith(self.categ_id.parent_path)
            )

        # Rule targets a specific template/variant.
        if product._name == "product.template":
            if self.applied_on == "1_product":
                return product.id == self.product_tmpl_id.id
            if self.applied_on == "0_product_variant":
                # A template matches a variant rule only if it is its sole variant.
                return (
                    product.product_variant_count == 1
                    and product.product_variant_id.id == self.product_id.id
                )
            return True  # 3_global

        if self.applied_on == "1_product":
            return product.product_tmpl_id.id == self.product_tmpl_id.id
        if self.applied_on == "0_product_variant":
            return product.id == self.product_id.id
        return True  # 3_global

    def _compute_price(
        self, product, quantity, uom, date, currency=None, *, base_price=None, **kwargs
    ):
        """Compute the unit price of a product in the context of a pricelist application.

        Note: self and self.ensure_one()

        :param product: recordset of product (product.product/product.template)
        :param float quantity: quantity of products requested (in given uom)
        :param uom: unit of measure (uom.uom record)
        :param datetime date: date to use for price computation and currency conversions
        :param currency: currency (for the case where self is empty)
        :param float base_price: base price already computed (in ``currency``) by the
            caller, used to skip the per-product `_compute_base_price` call. Callers
            that price several products at once (see
            :meth:`~product.pricelist._compute_chained_base_prices`) precompute it in
            batch; when ``None`` it is computed here as usual.
        :param dict kwargs: unused parameters available for overrides

        :returns: price according to pricelist rule or the product price, expressed in the param
                  currency, the pricelist currency or the company currency
        :rtype: float
        """
        self and self.ensure_one()  # self is at most one record
        product.ensure_one()
        uom.ensure_one()

        currency = currency or self.currency_id or self.env.company.currency_id
        currency.ensure_one()

        # Rule amounts (fixed price, surcharge, margins) are stored in the rule's
        # own currency and per the product's default UoM. Convert both to the
        # requested currency & UoM before combining them with the base price
        # (which _compute_base_price already returns in `currency`).
        product_uom_id = product.uom_id
        rule_currency = self.currency_id or currency

        def convert(price):
            if rule_currency != currency:
                price = rule_currency._convert(
                    price, currency, self.env.company, date, round=False
                )
            if product_uom_id != uom:
                price = product_uom_id._compute_price(price, uom)
            return price

        if self.compute_price == "fixed":
            return convert(self.fixed_price)

        # Every remaining branch prices off the base price; compute it once.
        if base_price is None:
            base_price = self._compute_base_price(
                product, quantity, uom, date, currency, **kwargs
            )

        if self.compute_price == "percentage":
            return base_price - (base_price * (self.percent_price / 100))

        if self.compute_price == "formula":
            price_limit = base_price
            # price_markup is -price_discount, so both are equal here.
            discount = self.price_discount
            price = base_price - (base_price * (discount / 100))
            if self.price_round:
                # price_round is expressed in the rule's currency & UoM like every
                # other rule amount, so convert it before rounding the (already
                # converted) price - otherwise the rounding grid is mis-scaled for
                # cross-currency / cross-UoM applications.
                price = float_round(price, precision_rounding=convert(self.price_round))
            if self.price_surcharge:
                price += convert(self.price_surcharge)
            if self.price_min_margin:
                price = max(price, price_limit + convert(self.price_min_margin))
            if self.price_max_margin:
                price = min(price, price_limit + convert(self.price_max_margin))
            return price

        # Empty self, or extended pricelist price computation logic.
        return base_price

    def _compute_base_price(self, product, quantity, uom, date, currency, **kwargs):
        """Compute the base price for a given rule.

        :param product: recordset of product (product.product/product.template)
        :param float quantity: quantity of products requested (in given uom)
        :param uom: unit of measure (uom.uom record)
        :param datetime date: date to use for price computation and currency conversions
        :param currency: currency in which the returned price must be expressed

        :returns: base price, expressed in provided pricelist currency
        :rtype: float
        """
        currency.ensure_one()

        rule_base = self.base or "list_price"
        if rule_base == "pricelist" and self.base_pricelist_id:
            price = self.base_pricelist_id._get_product_price(
                product,
                quantity,
                currency=self.base_pricelist_id.currency_id,
                uom=uom,
                date=date,
                **kwargs,
            )
            src_currency = self.base_pricelist_id.currency_id
        elif rule_base == "standard_price":
            src_currency = product.cost_currency_id
            price = product._price_compute(rule_base, uom=uom, date=date)[product.id]
        else:  # list_price
            src_currency = product.currency_id
            price = product._price_compute(rule_base, uom=uom, date=date)[product.id]

        if src_currency != currency:
            price = src_currency._convert(
                price, currency, self.env.company, date, round=False
            )

        return price

    def _compute_price_before_discount(
        self, product, quantity, uom, date, currency=None, **kwargs
    ):
        """Compute the base price of the given rule, considering chained pricelists.

        :param product: recordset of product (product.product/product.template)
        :param float qty: quantity of products requested (in given uom)
        :param uom: unit of measure (uom.uom record)
        :param datetime date: date to use for price computation and currency conversions
        :param currency: currency in which the returned price must be expressed

        :returns: base price, expressed in provided pricelist currency
        :rtype: float
        """
        pricelist_item = self
        # Find the lowest pricelist rule whose pricelist is configured to show
        # the discount to the customer.
        while pricelist_item.base == "pricelist":
            rule_id = pricelist_item.base_pricelist_id._get_product_rule(
                product, quantity, currency=currency, uom=uom, date=date, **kwargs
            )
            rule_pricelist_item = self.env["product.pricelist.item"].browse(rule_id)
            if (
                rule_pricelist_item
                and rule_pricelist_item.compute_price == "percentage"
            ):
                pricelist_item = rule_pricelist_item
            else:
                break

        return pricelist_item._compute_base_price(
            product, quantity, uom, date, currency, **kwargs
        )
