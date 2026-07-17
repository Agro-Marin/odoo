from collections import defaultdict
from datetime import datetime, time

from dateutil.relativedelta import relativedelta
from pytz import UTC

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT, SQL, get_lang
from odoo.tools.translate import _


class PurchaseOrderLine(models.Model):
    _name = "purchase.order.line"
    _inherit = [
        "order.line.fields.mixin",
        "order.line.amount.mixin",
        "order.line.invoice.mixin",
        "analytic.mixin",
    ]
    _description = "Purchase Order Line"
    _check_company_auto = True
    _order = "order_id, sequence, id"
    _rec_names_search = ["name", "order_id.name"]

    def _get_order_type(self):
        return "purchase"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    order_id = fields.Many2one(
        comodel_name="purchase.order",
        string="Order Reference",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        related="order_id.company_id",
        comodel_name="res.company",
        string="Company",
        store=True,
        precompute=True,
        readonly=True,
        index=True,
    )
    company_price_include = fields.Selection(
        related="company_id.account_price_include",
    )
    currency_id = fields.Many2one(
        related="order_id.currency_id",
        comodel_name="res.currency",
        string="Currency",
        store=True,
        precompute=True,
        depends=["order_id.currency_id"],
    )
    partner_id = fields.Many2one(
        related="order_id.partner_id",
        comodel_name="res.partner",
        string="Vendor",
        store=True,
        precompute=True,
        index="btree_not_null",
    )
    user_id = fields.Many2one(
        related="order_id.user_id",
        comodel_name="res.users",
        string="Buyer",
        store=True,
        precompute=True,
        index="btree_not_null",
    )
    date_order = fields.Datetime(
        related="order_id.date_order",
        string="Order Date",
        store=True,
        precompute=True,
        index=True,
    )
    date_confirmed = fields.Datetime(
        related="order_id.date_confirmed",
        string="Confirmation Date",
        store=True,
        precompute=True,
        index=True,
    )
    state = fields.Selection(
        related="order_id.state",
        string="Order Status",
        store=True,
        precompute=True,
    )
    fiscal_position_id = fields.Many2one(
        related="order_id.fiscal_position_id",
        comodel_name="account.fiscal.position",
    )
    locked = fields.Boolean(
        related="order_id.locked",
    )
    is_expense = fields.Boolean(
        help="Is true if the sales order line comes from an expense or a vendor bills",
    )

    # Section-related fields
    parent_id = fields.Many2one(
        comodel_name="purchase.order.line",
        string="Parent Section Line",
        compute="_compute_parent_id",
    )

    product_categ_id = fields.Many2one(
        related="product_id.categ_id",
    )
    product_type = fields.Selection(
        related="product_id.type",
        depends=["product_id"],
    )
    purchase_line_warn_msg = fields.Text(
        compute="_compute_purchase_line_warn_msg",
    )
    product_no_variant_attribute_value_ids = fields.Many2many(
        comodel_name="product.template.attribute.value",
        string="Product attribute values that do not create variants",
        ondelete="restrict",
    )
    # Only these attributes differ from order.line.amount.mixin.
    tax_ids = fields.Many2many(
        compute="_compute_tax_ids",
        store=True,
        precompute=True,
        readonly=False,
        domain="[('type_tax_use', '=', 'purchase')]",
    )
    selected_seller_id = fields.Many2one(
        comodel_name="product.supplierinfo",
        compute="_compute_selected_seller_id",
        store=True,
        precompute=True,
        help="The vendor pricelist entry that applies to this line based on "
        "partner, product, quantity, UoM, and date.",
    )
    price_unit_auto = fields.Float(
        help="Price from vendor/product. Compared with price_unit to detect manual overrides. "
        "When price_unit != price_unit_auto, the price is considered manually set.",
    )
    price_unit_product_uom = fields.Float(
        string="Unit Price Product UoM",
        min_display_digits="Product Price",
        compute="_compute_price_unit_product_uom",
        help="The Price of one unit of the product's Unit of Measure",
    )
    # Only this attribute differs from order.line.amount.mixin.
    discount = fields.Float(
        aggregator="avg",
    )
    date_planned = fields.Datetime(
        string="Expected Arrival",
        compute="_compute_date_planned",
        store=True,
        precompute=True,
        readonly=False,
        index=True,
        help="Delivery date expected from vendor. This date respectively defaults to vendor pricelist lead time then today's date.",
    )
    date_is_manual = fields.Boolean(
        string="Date Manually Set",
        default=False,
        help="If checked, the expected arrival date was manually set and won't be "
        "automatically updated when the seller or order date changes.",
    )
    # Transfer block
    qty_transferred_method = fields.Selection(
        string="Received Qty Method",
        help="According to product configuration, the received quantity can be automatically computed by mechanism:\n"
        "  - Manual: the quantity is set manually on the line\n"
        "  - Stock Moves: the quantity comes from confirmed pickings\n",
    )
    qty_transferred = fields.Float(string="Received Qty")
    # Same than `qty_transferred` but non-stored and depending of the context.
    qty_transferred_at_date = fields.Float(string="Received")

    # Invoice block
    # Only these attributes differ from order.line.invoice.mixin.
    invoice_line_ids = fields.Many2many(
        relation="account_move_line_purchase_order_line_rel",
        column1="order_line_id",
        column2="move_line_id",
    )
    # Same than `qty_to_invoice` but non-stored and depending of the context.
    qty_invoiced_at_date = fields.Float(string="Billed")

    # ------------------------------------------------------------
    # CONSTRAINT METHODS
    # ------------------------------------------------------------

    # -------------------------------------------------------------------------
    # CRUD METHODS
    # -------------------------------------------------------------------------

    def _get_display_type_nullify_vals(self):
        return {**super()._get_display_type_nullify_vals(), "date_planned": False}

    def _get_count_id(self, query):
        # Grouping purchase order lines by analytic_distribution counts orders.
        return SQL("order_id")

    def _get_tracked_qty_fields(self):
        return [*super()._get_tracked_qty_fields(), "qty_transferred"]

    def _collect_qty_changes(self, vals, tracked_fields):
        if self.env.context.get("accrual_entry_date"):
            # Accrual entries adjust qty_transferred without user-facing tracking.
            tracked_fields = [f for f in tracked_fields if f != "qty_transferred"]
        return super()._collect_qty_changes(vals, tracked_fields)

    def _post_quantity_changes(self, field_name, changes):
        changes_by_order = defaultdict(list)
        for change in changes:
            changes_by_order[change["line"].order_id].append(change)
        for order, order_changes in changes_by_order.items():
            self._post_batched_quantity_changes(order, order_changes, field_name)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_confirmed(self):
        """Prevent deletion of confirmed order lines that have been invoiced or received.

        Validates that order lines can be deleted based on:
        - Order state (cannot delete from confirmed orders)
        - Invoice status (cannot delete invoiced lines)
        - Display type (sections/notes can always be deleted)
        """
        lines_to_block = self._check_line_unlink()
        if lines_to_block:
            # Get dynamic state description for better error messages
            state_description = dict(
                self._fields["state"]._description_selection(self.env),
            )
            # Use the state of the first blocked line for the error message
            state_label = state_description[lines_to_block[0].state]
            raise UserError(
                _(
                    "Cannot delete a purchase order line which is in state '%s'.\n"
                    "Once a purchase order is confirmed, you can't remove lines that have been "
                    "invoiced or received (we need to track if something gets invoiced or received).\n"
                    "Set the quantity to 0 instead.",
                    state_label,
                ),
            )

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------

    @api.depends("product_id.purchase_line_warn_msg")
    def _compute_purchase_line_warn_msg(self):
        has_warning_group = self.env.user.has_group("purchase.group_warning_purchase")
        for line in self:
            line.purchase_line_warn_msg = (
                line.product_id.purchase_line_warn_msg if has_warning_group else ""
            )

    @api.depends(
        "product_id",
        "product_id.uom_id",
        "product_id.uom_ids",
        "product_id.seller_ids",
        "product_id.seller_ids.product_uom_id",
    )
    def _compute_allowed_uom_ids(self):
        # Shared union lives in order.line.fields.mixin; this override only
        # carries purchase's extended @api.depends (seller UoM triggers). The
        # seller UoMs themselves are added via _get_extra_allowed_uoms.
        return super()._compute_allowed_uom_ids()

    def _get_extra_allowed_uoms(self):
        return self.product_id.seller_ids.filtered(
            lambda s: s.product_id.id in {False, self.product_id.id},
        ).product_uom_id

    @api.depends("company_id", "fiscal_position_id", "product_id")
    def _compute_tax_ids(self):
        # Shared logic in order.line.amount.mixin, routed to supplier_taxes_id
        # via _get_product_tax_field(). This override only carries the
        # purchase-specific @api.depends above (adds fiscal_position_id).
        return super()._compute_tax_ids()

    @api.depends("partner_id", "product_id")
    def _compute_product_uom_id(self):
        """Set product UOM from seller or product default.

        Shared skeleton (same reset condition) lives in
        ``order.line.fields.mixin``; this override only carries purchase's
        extended ``@api.depends`` (partner). The default UoM is supplied via
        ``_get_default_product_uom``.
        """
        return super()._compute_product_uom_id()

    def _get_default_product_uom(self):
        # Seller's UoM for this partner, else the product's default UoM.
        seller_uom = False
        sellers = self._get_sellers_for_partner()
        if sellers and sellers[0].product_uom_id:
            seller_uom = sellers[0].product_uom_id
        return seller_uom or self.product_id.uom_id

    @api.depends(
        "partner_id", "date_order", "product_id", "product_id.seller_ids.min_qty"
    )
    def _compute_product_qty(self):
        """Set suggested quantity based on vendor's minimum order quantity.

        Shared skeleton lives in ``order.line.amount.mixin``; this override only
        carries purchase's extended ``@api.depends`` (partner/date/seller min
        qty). The reset condition and default are supplied via
        ``_product_qty_reset_triggered`` and ``_get_default_product_qty``.
        """
        return super()._compute_product_qty()

    def _product_qty_reset_triggered(self):
        # Reset on product change (mixin default) or, for purchase, partner change.
        return bool(
            (self._origin.product_id and self._origin.product_id != self.product_id)
            or (self._origin.partner_id and self._origin.partner_id != self.partner_id)
        )

    def _get_default_product_qty(self):
        # Seller's minimum quantity for this partner/date, else 1.0.
        date = fields.Date.context_today(self, timestamp=self.date_order)
        sellers = self._get_sellers_for_partner(date=date)
        # Further filter by product variant if specified
        sellers = sellers.filtered(
            lambda s: not s.product_id or s.product_id == self.product_id
        ).sorted(key=lambda r: r.min_qty)
        if sellers:
            return sellers[0].min_qty or 1.0
        return 1.0

    @api.depends(
        "partner_id",
        "date_order",
        "product_id",
        "product_id.seller_ids",
        "product_id.seller_ids.partner_id",
        "product_id.seller_ids.company_id",
        "product_id.seller_ids.min_qty",
        "product_id.seller_ids.date_start",
        "product_id.seller_ids.date_end",
        "product_id.seller_ids.product_uom_id",
        "product_uom_id",
        "product_qty",
        "company_id",
    )
    def _compute_selected_seller_id(self):
        """Select the best matching vendor pricelist entry.

        Selection criteria (handled by product._select_seller):
        - Partner matches (or parent partner)
        - Quantity >= min_qty
        - Date within validity period
        - UoM matches (if force_uom)
        - Sequence/priority ordering

        Performance optimization: Groups lines by (product, partner, order, uom)
        to cache seller lookups and avoid redundant _select_seller calls.
        For 200 lines with same product/partner, this reduces calls from 200 to 1.
        """
        # Handle non-accountable lines first
        non_accountable = self.filtered(lambda l: l.display_type or not l.product_id)
        non_accountable.selected_seller_id = False

        accountable_lines = self - non_accountable
        if not accountable_lines:
            return

        # Cache seller lookups by (product, partner, order, uom) to avoid redundant calls
        # We include order_id because date_order affects seller selection
        seller_cache = {}

        for line in accountable_lines:
            # Build cache key from factors that affect seller selection
            # Note: We use exact quantity (not bucketed) to ensure correct seller
            # selection based on min_qty thresholds. The cache still provides
            # benefit when multiple lines have identical quantities.
            qty = abs(line.product_qty) or 1.0

            cache_key = (
                line.product_id.id,
                line.partner_id.id,
                line.order_id.id,  # Includes date_order context
                line.product_uom_id.id,
                qty,  # Use exact quantity to respect min_qty thresholds
            )

            if cache_key not in seller_cache:
                params = line._get_select_sellers_params()
                # Rank sellers in the order's company: _select_seller converts
                # each seller's price with env.company.currency_id, so without
                # with_company a cross-company compute can pick the wrong vendor.
                # (order_id is already in cache_key, so it disambiguates company.)
                seller = line.product_id.with_company(line.company_id)._select_seller(
                    partner_id=line.partner_id,
                    quantity=qty,
                    date=fields.Date.context_today(
                        line, timestamp=line.order_id.date_order
                    ),
                    uom_id=line.product_uom_id,
                    params=params,
                )
                seller_cache[cache_key] = seller or False

            line.selected_seller_id = seller_cache[cache_key]

    @api.depends("partner_id", "product_id", "selected_seller_id")
    def _compute_name(self):
        """Compute product description from product/seller context.

        Sets the line description using the product name in the partner's language,
        with seller-specific context when available.
        """
        for line in self:
            if not line.product_id:
                continue
            line._set_product_description()

    def _get_line_description_lang(self):
        return self.partner_id.lang

    @api.depends(
        "selected_seller_id",
        "selected_seller_id.price",
        "selected_seller_id.discount",
        "selected_seller_id.currency_id",
        "selected_seller_id.product_uom_id",
        "product_id.standard_price",
        "product_id.supplier_taxes_id",
        "product_id.cost_currency_id",
        "product_uom_id",
        "company_id",
        "currency_id",
        "date_order",
        "tax_ids",
    )
    def _compute_price_and_discount(self):
        return super()._compute_price_and_discount()

    def _get_auto_price_and_discount(self):
        if self.selected_seller_id:
            return (
                self._get_price_from_seller(),
                self.selected_seller_id.discount or 0.0,
            )
        return self._get_price_from_product_cost(), 0.0

    @api.depends("date_order", "selected_seller_id", "selected_seller_id.delay")
    def _compute_date_planned(self):
        """Compute expected delivery date from order date and seller lead time.

        The date is calculated as: order_date + seller_delay (in days).
        If no seller is selected, only the order date is used.

        Uses date_is_manual flag to preserve user-set values. When date_is_manual
        is False, the date is automatically updated when seller or order date changes.
        """
        # Skip non-accountable lines
        accountable_lines = self.filtered(lambda l: not l.display_type and l.product_id)
        if not accountable_lines:
            return

        for line in accountable_lines:
            new_date = line._get_date_planned(line.selected_seller_id)

            # Not set yet - use the computed date
            if not line.date_planned:
                line.date_planned = new_date.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                continue

            # Already equals the new computed date - nothing to do
            if line.date_planned.date() == new_date.date():
                continue

            # Product changed from origin - always update (reset manual flag too)
            if line._origin.product_id and line._origin.product_id != line.product_id:
                line.date_planned = new_date.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                line.date_is_manual = False
                continue

            # Respect manual override flag
            if line.date_is_manual:
                continue

            # For backward compatibility: check if current date matches any seller's date
            # This handles existing records that don't have date_is_manual set
            if not line._origin.date_is_manual:
                valid_dates = line._get_seller_valid_dates()
                if line.date_planned.date() in valid_dates:
                    # Current date matches a known seller default - update it
                    line.date_planned = new_date.strftime(
                        DEFAULT_SERVER_DATETIME_FORMAT
                    )

    @api.depends("product_id.uom_id", "product_uom_id", "price_unit")
    def _compute_price_unit_product_uom(self):
        for line in self:
            line.price_unit_product_uom = (
                not line.display_type
                and not line.is_downpayment
                and line.product_uom_id._compute_price(
                    line.price_unit,
                    line.product_id.uom_id,
                )
            )

    @api.depends("product_qty", "price_unit", "discount", "tax_ids")
    def _compute_amounts(self):
        AccountTax = self.env["account.tax"]
        for line in self:
            if line.display_type:
                line.price_subtotal = False
                line.price_total = False
                line.price_tax = False
                continue
            company = line.company_id or self.env.company
            base_line = line._prepare_base_line_for_taxes_computation()
            AccountTax._add_tax_details_in_base_line(base_line, company)
            AccountTax._round_base_lines_tax_details([base_line], company)
            line.price_subtotal = base_line["tax_details"]["total_excluded_currency"]
            line.price_total = base_line["tax_details"]["total_included_currency"]
            line.price_tax = line.price_total - line.price_subtotal

    @api.depends(
        "state",
        "product_id.bill_policy",
        "product_qty",
        "price_unit_discounted_taxexc",
        "tax_ids",
        "price_total",
        "qty_transferred",
        "invoice_line_ids",
        "invoice_line_ids.parent_state",
        "invoice_line_ids.quantity",
        "invoice_line_ids.discount",
        "invoice_line_ids.price_subtotal",
        "invoice_line_ids.price_total",
    )
    def _compute_invoice_amounts(self):
        """Unified computation of all invoice-related quantities and amounts.

        Computes in single pass over invoice lines (for performance):
        - qty_invoiced, qty_to_invoice
        - amount_taxexc_invoiced, amount_taxexc_to_invoice
        - amount_taxinc_invoiced, amount_taxinc_to_invoice
        """
        for line in self:
            line._compute_invoice_amounts_single()

    def _compute_invoice_amounts_single(self):
        """Compute invoice amounts for a single purchase order line."""
        if self.display_type:
            self._reset_invoice_amounts()
            return

        invoice_lines = self._get_posted_invoice_lines()
        invoiced = self._sum_invoiced_amounts(invoice_lines)

        self.qty_invoiced = invoiced["qty"]
        self.amount_taxexc_invoiced = invoiced["amount_taxexc"]
        self.amount_taxinc_invoiced = invoiced["amount_taxinc"]

        if self.state in ("draft", "cancel"):
            self._reset_to_invoice_amounts()
            return

        self._compute_to_invoice_amounts(invoice_lines, invoiced)

    def _compute_to_invoice_amounts(self, invoice_lines, invoiced):
        """Compute the 'to invoice' quantities and amounts.

        Args:
            invoice_lines: recordset of posted invoice lines
            invoiced: dict with {qty, amount_taxexc, amount_taxinc} already invoiced
        """
        qty_to_consider = self._get_qty_to_consider_for_billing()
        price_subtotal = self._get_billable_subtotal(qty_to_consider)

        # Handle discount differences between PO line and invoice lines
        if self._has_discount_differences(invoice_lines):
            amount_invoiced = self._sum_invoiced_with_discount_adjustment(invoice_lines)
            self.amount_taxexc_to_invoice = max(price_subtotal - amount_invoiced, 0.0)
        else:
            self.amount_taxexc_to_invoice = max(
                price_subtotal - invoiced["amount_taxexc"],
                0.0,
            )

        # Tax-included: use unit price from price_total to avoid recalculation
        unit_price_total = (
            self.price_total / self.product_qty if self.product_qty else 0.0
        )
        self.amount_taxinc_to_invoice = unit_price_total * (
            qty_to_consider - invoiced["qty"]
        )
        self.qty_to_invoice = qty_to_consider - invoiced["qty"]

    @api.depends_context("accrual_entry_date")
    @api.depends("price_unit", "qty_invoiced_at_date", "qty_transferred_at_date")
    def _compute_amount_to_invoice_at_date(self):
        for line in self:
            line.amount_to_invoice_at_date = (
                line.qty_transferred_at_date - line.qty_invoiced_at_date
            ) * line._get_price_unit_gross()

    @api.depends(
        "qty_to_invoice",
        "qty_invoiced",
        "product_qty",
        "qty_transferred",
        "product_id.bill_policy",
        "amount_taxexc_to_invoice",
    )
    def _compute_invoice_state(self):
        # Shared logic in order.line.invoice.mixin, keyed on bill_policy via
        # _get_invoice_policy_field(). This override only carries the
        # purchase-specific @api.depends above.
        return super()._compute_invoice_state()

    # -------------------------------------------------------------------------
    # ONCHANGE METHODS
    # -------------------------------------------------------------------------

    @api.onchange("date_planned")
    def _onchange_date_planned(self):
        """Mark date as manually set when user changes it in the UI.

        This flag prevents automatic date updates when seller or order date
        changes, preserving the user's explicit choice.
        """
        if self._origin.date_planned and self.date_planned != self._origin.date_planned:
            self.date_is_manual = True

    # -------------------------------------------------------------------------
    # HELPER METHODS
    # -------------------------------------------------------------------------

    def _convert_to_middle_of_day(self, date):
        """Return a datetime which is the noon of the input date(time) according
        to order user's time zone, convert to UTC time.
        """
        return (
            self.order_id.get_timezone()
            .localize(datetime.combine(date, time(12)))
            .astimezone(UTC)
            .replace(tzinfo=None)
        )

    def _get_billable_subtotal(self, qty):
        """Calculate the billable subtotal for a given quantity.

        Handles price-included taxes by using compute_all() to extract
        the tax-excluded amount.

        Note: Cannot use price_subtotal field directly because it returns zero
        when product_qty is zero, which breaks expense lines.

        Args:
            qty: Quantity to calculate subtotal for

        Returns:
            float: Tax-excluded subtotal amount
        """
        subtotal = self.price_unit_discounted_taxexc * qty

        if self.tax_ids.filtered(lambda t: t.price_include):
            subtotal = self.tax_ids.compute_all(
                self.price_unit_discounted_taxexc,
                currency=self.currency_id,
                quantity=qty,
                product=self.product_id,
                partner=self.order_id.partner_id,
            )["total_excluded"]

        return subtotal

    @api.model
    def _get_date_planned(self, seller, po=False):
        """Return the datetime value to use as Schedule Date (``date_planned``) for
        PO Lines that correspond to the given product.seller_ids,
        when ordered at `date_order_str`.

        :param Model seller: used to fetch the delivery delay (if no seller
                             is provided, the delay is 0)
        :param Model po: purchase.order, necessary only if the PO line is
                         not yet attached to a PO.
        :rtype: datetime
        :return: desired Schedule Date for the PO line
        """
        date_order = po.date_order if po else self.order_id.date_order
        if date_order:
            return date_order + relativedelta(days=seller.delay if seller else 0)
        else:
            return datetime.today() + relativedelta(days=seller.delay if seller else 0)

    def _get_line_description(self, product_lang):
        """Compute a default description for this purchase order line.

        :param product_lang: product record with proper language context
        :return: the description for the purchase order line
        :rtype: string
        """
        self.ensure_one()
        name = product_lang.display_name
        if product_lang.description_purchase:
            name += "\n" + product_lang.description_purchase
        no_variant_attribute_values = self.with_context(
            product_lang.env.context,
        ).product_no_variant_attribute_value_ids
        for no_variant_attribute_value in no_variant_attribute_values:
            name += (
                "\n"
                + no_variant_attribute_value.attribute_id.name
                + ": "
                + no_variant_attribute_value.name
            )
        return name

    def _get_price_precision(self):
        """Get precision for price rounding.

        Returns the maximum between currency decimal places and
        the system's Product Price decimal precision.
        """
        self.ensure_one()
        return max(
            self.currency_id.decimal_places,
            self.env["decimal.precision"].precision_get("Product Price"),
        )

    def _get_catalog_single_line_data(self, **kwargs):
        catalog_info = self.order_id._get_product_price_and_data(self.product_id)
        catalog_info.update(
            quantity=self.product_qty,
            price=self.price_unit * (1 - self.discount / 100),
            readOnly=self.order_id._is_readonly(),
        )
        if self.product_id.uom_id != self.product_uom_id:
            catalog_info["uomDisplayName"] = self.product_uom_id.display_name
        return catalog_info

    def _get_catalog_multi_line_data(self, **kwargs):
        return self.order_id._get_product_price_and_data(self.product_id)

    def _get_price_from_seller(self):
        """Get price from selected seller's pricelist.

        Includes:
        - Tax adjustments
        - Currency conversion
        - UoM conversion

        Returns:
            float: The computed price unit
        """
        self.ensure_one()
        seller = self.selected_seller_id

        # Get seller's base price, adjust for tax inclusion
        price_unit = self.env["account.tax"]._fix_tax_included_price_company(
            seller.price,
            self.product_id.supplier_taxes_id,
            self.tax_ids,
            self.company_id,
        )

        # Convert currency
        price_unit = seller.currency_id._convert(
            price_unit,
            self.currency_id,
            self.company_id,
            self.date_order or fields.Date.context_today(self),
            False,
        )

        # Convert UoM
        return seller.product_uom_id._compute_price(price_unit, self.product_uom_id)

    def _get_price_from_product_cost(self):
        """Get price from product standard cost (fallback when no seller).

        Includes:
        - UoM conversion to line UoM
        - Tax adjustments
        - Currency conversion

        Returns:
            float: The computed price unit
        """
        self.ensure_one()

        # Determine UoM for pricing
        po_line_uom = self.product_uom_id or self.product_id.uom_id

        # Convert product cost to line UoM and adjust for taxes
        price_unit = self.env["account.tax"]._fix_tax_included_price_company(
            self.product_id.uom_id._compute_price(
                self.product_id.standard_price,
                po_line_uom,
            ),
            self.product_id.supplier_taxes_id,
            self.tax_ids,
            self.company_id,
        )

        # Convert from product cost currency to line currency
        return self.product_id.cost_currency_id._convert(
            price_unit,
            self.currency_id,
            self.company_id,
            self.date_order or fields.Date.context_today(self),
            False,
        )

    def _get_qty_to_consider_for_billing(self):
        """Get quantity to consider based on product's billing policy.

        Returns:
            float: qty_transferred if bill_policy is 'transferred', else product_qty
        """
        if self.product_id.bill_policy == "transferred":
            return self.qty_transferred
        return self.product_qty

    def _get_select_sellers_params(self):
        self.ensure_one()
        return {
            "order_id": self.order_id,
            "force_uom": True,
        }

    def _get_sellers_for_partner(self, date=None):
        """Get filtered sellers matching this line's partner and optional date.

        Centralizes the seller filtering logic used across multiple compute methods.
        Filters sellers by:
        - Partner matches (direct or parent company)
        - Date within validity period (if date provided)

        :param date: Optional date for validity check (date object or None)
        :return: Filtered recordset of product.supplierinfo
        :rtype: recordset
        """
        self.ensure_one()
        if not self.product_id or not self.partner_id:
            return self.env["product.supplierinfo"]

        sellers = self.product_id.seller_ids

        # Filter by partner (direct or parent company)
        partner = self.partner_id
        parent = self.partner_id.parent_id
        sellers = sellers.filtered(lambda s: s.partner_id in (partner, parent))

        # Filter by date validity if provided
        if date:
            sellers = sellers.filtered(
                lambda s: (
                    (not s.date_start or s.date_start <= date)
                    and (not s.date_end or s.date_end >= date)
                )
            )

        return sellers

    def _get_seller_valid_dates(self):
        """Get set of all valid planned dates from product's sellers.

        Computes the expected delivery date for each seller on this product,
        plus the no-seller default (order date only). Returns as a set for
        O(1) membership testing.

        :return: Set of date objects representing valid auto-computed dates
        :rtype: set
        """
        self.ensure_one()
        valid_dates = set()

        # Add date from each seller's delay
        for seller in self.product_id.seller_ids:
            seller_date = self._get_date_planned(seller)
            valid_dates.add(seller_date.date())

        # Add the no-seller default (order date with 0 delay)
        no_seller_date = self._get_date_planned(False)
        valid_dates.add(no_seller_date.date())

        return valid_dates

    def _get_invoice_line_link_field(self):
        return "purchase_line_ids"

    def _invoiced_on_transferred(self):
        return self.product_id.bill_policy == "transferred"

    def _prepare_aml_vals(self, **optional_values):
        """Prepare the values to create the new invoice line for a purchase order line.

        Extends the shared mixin dict with purchase specifics: the ``move``
        context (used for currency/date, not as a field), the currency
        conversion of ``price_unit``, and the refund quantity sign.

        :param optional_values: any parameter that should be added to the returned invoice line
        :rtype: dict
        """
        self.ensure_one()
        # Pop 'move' as it's only used for context (currency, date), not as a field
        move = optional_values.pop("move", None)
        res = super()._prepare_aml_vals(**optional_values)
        aml_currency = (move and move.currency_id) or self.currency_id
        date = (move and move.date) or fields.Date.today()
        res["quantity"] = (
            -self.qty_to_invoice
            if move and move.move_type == "in_refund"
            else self.qty_to_invoice
        )
        res["price_unit"] = self.currency_id._convert(
            self.price_unit,
            aml_currency,
            self.company_id,
            date,
            round=False,
        )
        return res

    def _post_batched_quantity_changes(self, order, changes, change_type):
        """Post a single batched message for quantity changes.

        :param order: purchase.order record
        :param changes: list of dicts with 'line', 'old_qty', 'new_qty' keys
        :param change_type: 'product_qty' or 'qty_transferred'
        """
        if not changes:
            return

        if len(changes) == 1:
            # Single line change - use original template for compatibility
            change = changes[0]
            if change_type == "product_qty":
                order.message_post_with_source(
                    "purchase.track_po_line_template",
                    render_values={
                        "line": change["line"],
                        "product_qty": change["new_qty"],
                    },
                    subtype_xmlid="mail.mt_note",
                )
            elif change_type == "qty_transferred":
                order.message_post_with_source(
                    "purchase.track_po_line_qty_transferred_template",
                    render_values={
                        "line": change["line"],
                        "qty_transferred": change["new_qty"],
                    },
                    subtype_xmlid="mail.mt_note",
                )
        else:
            # Multiple lines - use consolidated order-level template
            order.message_post_with_source(
                "purchase.track_po_qty_update_template",
                render_values={
                    "changes": changes,
                    "change_type": change_type,
                    "count": len(changes),
                },
                subtype_xmlid="mail.mt_note",
            )

    @api.model
    def _prepare_purchase_order_line(
        self,
        product_id,
        product_qty,
        product_uom_id,
        company_id,
        partner_id,
        po,
    ):
        values = self.env.context.get("procurement_values", {})
        uom_po_qty = product_uom_id._compute_quantity(
            product_qty,
            product_id.uom_id,
            rounding_method="HALF-UP",
        )
        # _select_seller is used if the supplier have different price depending
        # the quantities ordered.
        today = fields.Date.context_today(self)
        seller = product_id.with_company(company_id)._select_seller(
            partner_id=partner_id,
            quantity=product_qty if values.get("force_uom") else uom_po_qty,
            date=max(fields.Date.context_today(self, timestamp=po.date_order), today),
            uom_id=product_uom_id if values.get("force_uom") else product_id.uom_id,
            params={"force_uom": values.get("force_uom")},
        )
        if (
            seller
            and (seller.product_uom_id or seller.product_tmpl_id.uom_id)
            != product_uom_id
        ):
            uom_po_qty = product_id.uom_id._compute_quantity(
                uom_po_qty,
                seller.product_uom_id,
                rounding_method="HALF-UP",
            )

        tax_domain = self.env["account.tax"]._check_company_domain(company_id)
        product_taxes = product_id.supplier_taxes_id.filtered_domain(tax_domain)
        taxes = po.fiscal_position_id.map_tax(product_taxes)

        if seller:
            price_unit = (
                seller.product_uom_id._compute_price(seller.price, product_uom_id)
                if product_uom_id
                else seller.price
            )
            price_unit = self.env["account.tax"]._fix_tax_included_price_company(
                price_unit,
                product_taxes,
                taxes,
                company_id,
            )
        else:
            price_unit = 0
        if (
            price_unit
            and seller
            and po.currency_id
            and seller.currency_id != po.currency_id
        ):
            price_unit = seller.currency_id._convert(
                price_unit,
                po.currency_id,
                po.company_id,
                po.date_order or fields.Date.today(),
            )

        product_lang = product_id.with_prefetch().with_context(
            lang=partner_id.lang,
            partner_id=partner_id.id,
        )
        name = product_lang.with_context(seller_id=seller.id).display_name
        if product_lang.description_purchase:
            name += "\n" + product_lang.description_purchase

        date_planned = self.order_id.date_planned or self._get_date_planned(
            seller,
            po=po,
        )
        discount = seller.discount or 0.0

        return {
            "name": name,
            "product_qty": product_qty if product_uom_id else uom_po_qty,
            "product_id": product_id.id,
            "product_uom_id": product_uom_id.id or seller.product_uom_id.id,
            "price_unit": price_unit,
            "date_planned": date_planned,
            "tax_ids": [Command.set(taxes.ids)],
            "order_id": po.id,
            "discount": discount,
        }

    def _reset_invoice_amounts(self):
        """Reset all invoice-related amounts to zero (for display_type lines)."""
        self.qty_invoiced = False
        self.qty_to_invoice = False
        self.amount_taxexc_invoiced = False
        self.amount_taxexc_to_invoice = False
        self.amount_taxinc_invoiced = False
        self.amount_taxinc_to_invoice = False

    def _reset_to_invoice_amounts(self):
        """Reset 'to invoice' amounts to zero (for draft/cancel states)."""
        self.amount_taxexc_to_invoice = 0.0
        self.amount_taxinc_to_invoice = 0.0
        self.qty_to_invoice = 0.0

    def _set_product_description(self):
        """Set line description from product in partner's language.

        Uses selected seller context for vendor-specific descriptions.
        Updates when:
        - Name is empty
        - Product changed (user selected a different product)
        - Name matches a known default for current product (not manually customized)
        """
        self.ensure_one()

        lang = get_lang(self.env, self.partner_id.lang).code

        # Build product context with current seller
        seller_id = self.selected_seller_id.id if self.selected_seller_id else None
        product_ctx = {"seller_id": seller_id, "lang": lang}
        new_default = self._get_line_description(
            self.product_id.with_context(product_ctx),
        )

        # No name set yet, use the default
        if not self.name:
            self.name = new_default
            return

        # Name already equals new default - nothing to do
        if self.name == new_default:
            return

        # Always update if product changed from origin (different product = new description)
        if self._origin.product_id and self._origin.product_id != self.product_id:
            self.name = new_default
            return

        # Check if current name matches ANY seller's default description for CURRENT product
        # If so, it's not manually customized - update to new seller's description
        for seller in self.product_id.seller_ids:
            seller_ctx = {"seller_id": seller.id, "lang": lang}
            seller_default = self._get_line_description(
                self.product_id.with_context(seller_ctx),
            )
            if self.name == seller_default:
                # Current name is a seller default (not customized) - update it
                self.name = new_default
                return

        # Also check the no-seller default (generic product description)
        no_seller_ctx = {"seller_id": None, "lang": lang}
        generic_default = self._get_line_description(
            self.product_id.with_context(no_seller_ctx),
        )
        if self.name == generic_default:
            self.name = new_default
            return

        # Name was customized (differs from every default), but it may still start
        # with a known vendor's display-name prefix (e.g. "[Code 1] Name 1\n<note>").
        # In that case resync only the vendor code/name prefix to the currently
        # selected vendor (or to the no-vendor name) so it stays correct when the
        # partner/seller changes, while preserving the user's custom remainder.
        for seller in self.product_id.seller_ids:
            seller_display_name = self.product_id.with_context(
                {"seller_id": seller.id, "lang": lang},
            ).display_name
            if self.name.startswith(seller_display_name):
                if not self.selected_seller_id:
                    self.name = (
                        self.product_id.with_context(
                            {"seller_id": None, "lang": lang},
                        ).display_name
                        + self.name[len(seller_display_name) :]
                    )
                elif seller.id != self.selected_seller_id.id:
                    self.name = (
                        self.product_id.with_context(
                            {"seller_id": self.selected_seller_id.id, "lang": lang},
                        ).display_name
                        + self.name[len(seller_display_name) :]
                    )
                return

        # Name differs from all defaults - user customized it, preserve it

    def _sum_invoiced_amounts(self, invoice_lines):
        """Sum quantities and amounts from invoice lines in a single pass.

        Aggregates quantity, tax-excluded amount, and tax-included amount
        from all posted invoice lines, converting to line's UoM and currency.

        Args:
            invoice_lines: recordset of account.move.line

        Returns:
            dict: {qty, amount_taxexc, amount_taxinc}
        """
        qty = 0.0
        amount_taxexc = 0.0
        amount_taxinc = 0.0

        for inv_line in invoice_lines:
            sign = inv_line.move_id.direction_sign
            date = inv_line.invoice_date or fields.Date.today()

            qty += sign * inv_line.product_uom_id._compute_quantity(
                inv_line.quantity,
                self.product_uom_id,
            )
            amount_taxexc += sign * inv_line.currency_id._convert(
                inv_line.price_subtotal,
                self.currency_id,
                self.company_id,
                date,
            )
            amount_taxinc += sign * inv_line.currency_id._convert(
                inv_line.price_total,
                self.currency_id,
                self.company_id,
                date,
            )

        return {
            "qty": qty,
            "amount_taxexc": amount_taxexc,
            "amount_taxinc": amount_taxinc,
        }

    def _sum_invoiced_with_discount_adjustment(self, invoice_lines):
        """Sum invoiced amounts when discounts differ between PO and invoices.

        When re-invoicing with different discounts, calculate based on
        invoice line prices rather than aggregated amounts.

        Args:
            invoice_lines: recordset of account.move.line

        Returns:
            float: Total tax-excluded amount invoiced
        """
        total = 0.0

        for inv_line in invoice_lines:
            converted_price = inv_line.currency_id._convert(
                inv_line.price_unit,
                self.currency_id,
                self.company_id,
                inv_line.date or fields.Date.today(),
                round=False,
            )
            line_amount = converted_price * inv_line.quantity

            if inv_line.tax_ids.filtered(lambda t: t.price_include):
                line_amount = inv_line.tax_ids.compute_all(line_amount)[
                    "total_excluded"
                ]

            total += line_amount

        return total

    def _update_date_planned(self, updated_date):
        self.date_planned = updated_date

    # ------------------------------------------------------------
    # VALIDATIONS
    # ------------------------------------------------------------

    @api.model
    def _date_in_the_past(self):
        if "accrual_entry_date" not in self.env.context:
            return False
        accrual_date = fields.Date.from_string(self.env.context["accrual_entry_date"])
        return accrual_date and accrual_date < fields.Date.today()

    def _has_discount_differences(self, invoice_lines):
        """Check if any invoice line has a different discount than the PO line."""
        return any(inv_line.discount != self.discount for inv_line in invoice_lines)

    def _price_update_blocked(self):
        # Don't update if line is linked to invoices
        if self.invoice_line_ids:
            return True
        # On confirmed orders, block price updates when only currency changed
        # (prevents recalculation when changing display currency)
        if self.state == "done" and self._origin.id:
            original_currency = self._origin.currency_id
            if original_currency and original_currency != self.currency_id:
                return True
        return super()._price_update_blocked()

    def _validate_write_vals(self, write_vals):
        for method_name in self._get_validate_write_vals_methods():
            if hasattr(self, method_name):
                getattr(self, method_name)(write_vals)
