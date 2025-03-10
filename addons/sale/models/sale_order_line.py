from collections import defaultdict
from datetime import timedelta
from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command
from odoo.osv import expression
from odoo.tools import format_date, groupby
from odoo.tools.float_utils import float_compare, float_is_zero
from odoo.tools.translate import _


class SaleOrderLine(models.Model):
    """Manages an individual line item within a sales order.

    Handles product details, quantities, pricing, discounts, taxes, and subtotal calculations
    associated with each sales order line."""

    _name = "sale.order.line"
    _description = "Sales Order Line"
    _inherit = ["analytic.mixin"]
    _check_company_auto = True
    _order = "order_id, sequence, id"
    _rec_names_search = ["name", "order_id.name"]

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    order_id = fields.Many2one(
        comodel_name="sale.order",
        string="Order Reference",
        required=True,
        auto_join=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        related="order_id.company_id",
        string="Company",
        store=True,
        precompute=True,
        readonly=True,
        index=True,
    )
    company_price_include = fields.Selection(
        related="company_id.account_price_include",
        readonly=True,
        help="Technical computed field for UX purposes (hide/make fields readonly, invisible, ...)",
    )
    currency_id = fields.Many2one(
        related="order_id.currency_id",
        string="Currency",
        depends=["order_id.currency_id"],
        store=True,
        precompute=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        related="order_id.partner_id",
        string="Customer",
        store=True,
        precompute=True,
        readonly=True,
        index=True,
    )
    user_id = fields.Many2one(
        related="order_id.user_id",
        string="Salesperson",
        store=True,
        precompute=True,
        readonly=True,
    )
    date_order = fields.Datetime(
        related="order_id.date_order",
        string="Order Date",
        store=True,
        precompute=True,
        readonly=True,
        index=True,
    )
    state = fields.Selection(
        related="order_id.state",
        string="Order Status",
        store=True,
        precompute=True,
        readonly=True,
    )
    locked = fields.Boolean(
        related="order_id.locked",
    )
    sequence = fields.Integer(string="Sequence", default=10)
    display_type = fields.Selection(
        selection=[
            ("line_section", "Section"),
            ("line_note", "Note"),
        ],
        default=False,
        help="It specify custom line logic, whether is a product or just a text",
    )

    is_downpayment = fields.Boolean(
        string="Is a down payment",
        help="Down payments are made when creating invoices from a sales order."
        " They are not copied when duplicating a sales order.",
    )
    is_expense = fields.Boolean(
        string="Is expense",
        help="Is true if the sales order line comes from an expense or a vendor bills",
    )

    linked_line_ids = fields.One2many(
        comodel_name="sale.order.line",
        inverse_name="linked_line_id",
        string="Linked Order Lines",
    )
    linked_line_id = fields.Many2one(
        comodel_name="sale.order.line",
        string="Linked Order Line",
        domain="[('order_id', '=', order_id)]",
        ondelete="cascade",
        copy=False,
        index=True,
    )

    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        change_default=True,
        domain=[("sale_ok", "=", True)],
        ondelete="restrict",
        index="btree_not_null",
    )
    product_type = fields.Selection(
        related="product_id.type",
        depends=["product_id"],
        readonly=True,
        help="Technical computed field for UX purposes (hide/make fields readonly, invisible, ...)",
    )
    service_tracking = fields.Selection(
        related="product_id.service_tracking",
        depends=["product_id"],
        readonly=True,
        help="Technical computed field for UX purposes (hide/make fields readonly, invisible, ...)",
    )
    translated_product_name = fields.Text(
        compute="_compute_translated_product_name",
    )
    product_template_id = fields.Many2one(
        comodel_name="product.template",
        string="Product Template",
        compute="_compute_product_template_id",
        readonly=False,
        search="_search_product_template_id",
        # previously related='product_id.product_tmpl_id'
        # not anymore since the field must be considered editable for product configurator logic
        # without modifying the related product_id when updated.
        domain=[("sale_ok", "=", True)],
    )
    is_configurable_product = fields.Boolean(
        related="product_template_id.has_configurable_attributes",
        string="Is the product configurable?",
        depends=["product_id"],
    )
    product_template_attribute_value_ids = fields.Many2many(
        related="product_id.product_template_attribute_value_ids",
        depends=["product_id"],
    )
    product_custom_attribute_value_ids = fields.One2many(
        comodel_name="product.attribute.custom.value",
        inverse_name="sale_order_line_id",
        string="Custom Values",
        compute="_compute_custom_attribute_values",
        store=True,
        precompute=True,
        readonly=False,
        copy=True,
    )
    product_no_variant_attribute_value_ids = fields.Many2many(
        comodel_name="product.template.attribute.value",
        string="Extra Values",
        compute="_compute_no_variant_attribute_values",
        store=True,
        precompute=True,
        readonly=False,
        ondelete="restrict",
    )
    tax_ids = fields.Many2many(
        comodel_name="account.tax",
        string="Taxes",
        compute="_compute_tax_ids",
        store=True,
        precompute=True,
        readonly=False,
        check_company=True,
        context={"active_test": False},
        help="Is a pricing purpose field to specify taxes applied on the line.",
    )
    allowed_uom_ids = fields.Many2many(
        comodel_name="uom.uom",
        compute="_compute_allowed_uom_ids",
    )
    product_uom_id = fields.Many2one(
        comodel_name="uom.uom",
        string="Unit",
        compute="_compute_product_uom_id",
        store=True,
        precompute=True,
        readonly=False,
        domain=[("id", "in", allowed_uom_ids)],
        ondelete="restrict",
    )
    product_qty = fields.Float(
        string="Quantity",
        digits="Product Unit",
        # compute="_compute_product_uom_qty",
        # store=True,
        # precompute=True,
        # readonly=False,
    )
    product_uom_qty = fields.Float(
        string="Quantity",
        digits="Product Unit",
        compute="_compute_product_uom_qty",
        store=True,
        precompute=True,
        readonly=False,
    )
    pricelist_item_id = fields.Many2one(
        comodel_name="product.pricelist.item",
        compute="_compute_pricelist_item_id",
        help="Tech field caching pricelist rule used for price & discount computation",
    )
    name = fields.Text(
        string="Description",
        required=True,
        compute="_compute_name",
        store=True,
        precompute=True,
        readonly=False,
    )
    price_unit = fields.Float(
        string="Unit Price",
        digits="Product Price",
        compute="_compute_price_unit",
        store=True,
        precompute=True,
        readonly=False,
        aggregator="avg",
    )
    technical_price_unit = fields.Float(
        string="Technical Unit Price",
        digits="Product Price",
        readonly=True,
    )
    discount = fields.Float(
        string="Discount (%)",
        digits="Discount",
        compute="_compute_discount",
        store=True,
        precompute=True,
        readonly=False,
    )
    customer_lead = fields.Float(
        string="Lead Time",
        required=True,
        compute="_compute_customer_lead",
        store=True,
        precompute=True,
        readonly=False,
        help="Number of days between the order confirmation and the shipping of the products to the customer",
    )
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
    price_unit_discounted_taxexc = fields.Float(
        string="Unit Price (Discounted Tax Excluded)",
        digits="Product Price",
        compute="_compute_amounts",
        store=True,
        precompute=True,
    )
    price_unit_discounted_taxinc = fields.Float(
        string="Unit Price (Discounted Tax Included)",
        digits="Product Price",
        compute="_compute_amounts",
        store=True,
        precompute=True,
    )

    virtual_id = fields.Char(
        help="Uniquely identifies this sale order line before "
        "the record is saved in the DB, i.e. before the record has an `id`."
    )
    linked_virtual_id = fields.Char(
        help="Links this sale order line to another sale order line, via its `virtual_id`"
    )

    combo_item_id = fields.Many2one(comodel_name="product.combo.item")
    selected_combo_items = fields.Char(
        store=False,
        help="Local storage of this sale order line's selected combo items, iff this is a combo product line.",
    )

    # Transfer block
    qty_transfered_method = fields.Selection(
        selection=[
            ("manual", "Manual"),
            ("analytic", "Analytic From Expenses"),
            ("stock_move", "Stock Moves"),
        ],
        string="Method to update delivered qty",
        compute="_compute_qty_transfered_method",
        store=True,
        precompute=True,
        help="""According to product configuration, the delivered quantity can 
        be automatically computed by mechanism:\n
        -Manual: the quantity is set manually on the line\n
        -Analytic From expenses: the quantity is the quantity sum from posted expenses\n
        -Timesheet: the quantity is the sum of hours recorded on tasks linked to this sale line\n
        -Stock Moves: the quantity comes from confirmed pickings\n""",
    )
    qty_transfered = fields.Float(
        string="Transfered Qty",
        digits="Product Unit",
        default=0.0,
        compute="_compute_qty_transfered",
        store=True,
        readonly=False,
        copy=False,
    )

    # Invoice block
    invoice_line_ids = fields.Many2many(
        comodel_name="account.move.line",
        relation="account_move_line_sale_order_line_rel",
        column1="order_line_id",
        column2="move_line_id",
        string="Invoice Lines",
        copy=False,
    )
    qty_to_invoice = fields.Float(
        string="Quantity To Invoice",
        digits="Product Unit",
        compute="_compute_invoice_amounts",
        store=True,
        readonly=True,
    )
    qty_invoiced = fields.Float(
        string="Invoiced Quantity",
        digits="Product Unit",
        compute="_compute_invoice_amounts",
        store=True,
        readonly=True,
    )
    amount_to_invoice_taxinc = fields.Monetary(
        string="Un-invoiced Balance",
        compute="_compute_invoice_amounts",
        store=True,
        compute_sudo=True,
        readonly=True,
    )
    amount_to_invoice_taxexc = fields.Monetary(
        string="Untaxed Amount To Invoice",
        compute="_compute_invoice_amounts",
        store=True,
        compute_sudo=True,
        readonly=True,
    )
    amount_invoiced_taxexc = fields.Monetary(
        string="Untaxed Invoiced Amount",
        compute="_compute_invoice_amounts",
        store=True,
        compute_sudo=True,
        readonly=True,
    )
    amount_invoiced_taxinc = fields.Monetary(
        string="Invoiced Amount",
        compute="_compute_invoice_amounts",
        store=True,
        compute_sudo=True,
        readonly=True,
    )
    invoice_state = fields.Selection(
        selection=[
            ("no", "Nothing to invoice"),
            ("to do", "To invoice"),
            ("partially", "Partially invoiced"),
            ("done", "Fully invoiced"),
            ("over done", "Over invoiced"),
            ("upselling", "Upselling"),
        ],
        string="Invoice Status",
        default="no",
        compute="_compute_invoice_state",
        store=True,
    )

    is_product_archived = fields.Boolean(
        compute="_compute_is_product_archived",
    )
    product_updatable = fields.Boolean(
        string="Can edit product",
        compute="_compute_product_updatable",
    )
    product_uom_updatable = fields.Boolean(
        string="Can edit unit of measure",
        compute="_compute_product_uom_updatable",
    )

    # ------------------------------------------------------------
    # CONSTRAINT METHODS
    # ------------------------------------------------------------

    _accountable_required_fields = models.Constraint(
        """CHECK(
            display_type IS NOT NULL
            OR is_downpayment
            OR (
                product_id IS NOT NULL
                AND product_uom_id IS NOT NULL
            )
        )""",
        "Missing required fields on accountable sale order line.",
    )
    _non_accountable_null_fields = models.Constraint(
        """CHECK(
            display_type IS NULL
            OR (
                product_id IS NULL
                AND product_uom_qty = 0
                AND product_uom_id IS NULL
                AND price_unit = 0
                AND customer_lead = 0
            )
        )""",
        "Forbidden values on non-accountable sale order line",
    )

    @api.constrains("combo_item_id")
    def _check_combo_item_id(self):
        """`combo_item_id` should never be set manually. This constraint mainly serves to avoid
        programming errors."""
        for line in self:
            linked_line = line._get_line_linked()
            allowed_combo_items = (
                linked_line.product_template_id.combo_ids.combo_item_ids
            )
            if line.combo_item_id and line.combo_item_id not in allowed_combo_items:
                raise ValidationError(
                    _(
                        "A sale order line's combo item must be among its linked line's available"
                        " combo items."
                    )
                )
            if line.combo_item_id and line.combo_item_id.product_id != line.product_id:
                raise ValidationError(
                    _(
                        "A sale order line's product must match its combo item's product."
                    )
                )

    # ------------------------------------------------------------
    # CRUD METHODS
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        self._sanitize_create_display_type_vals(vals_list)

        res = super().create(vals_list)

        for line in res:
            linked_line = line._get_line_linked()
            if linked_line:
                line.linked_line_id = linked_line

        lines_confirmed = res.filtered(
            lambda l: l.state == "sale" and not l.display_type
        )
        lines_confirmed._hook_on_created_confirmed_lines()

        return res

    def write(self, vals):
        self._check_write_protected_fields(vals)
        self._check_write_display_type(vals)
        self._check_write_product_updatable(vals)
        self._sanitize_write_vals_technical_price_unit(vals)

        previous_vals = self._prepare_write_previous_vals(vals)

        res = super().write(vals)

        confirmed_lines = self.filtered(
            lambda l: l.order_id.state == "sale" and not l.display_type
        )
        confirmed_lines._hook_on_written_confirmed_lines(vals, previous_vals)

        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_confirmed(self):
        if self._cant_be_unlinked():
            raise UserError(
                _(
                    "Once a sales order is confirmed, you can't remove one of its lines "
                    "(we need to track if something gets invoiced or delivered).\n\
                    Set the quantity to 0 instead."
                )
            )

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    # This computed default is necessary to have a clean computation inheritance
    # (cf sale_stock) instead of simply removing the default and specifying
    # the compute attribute & method in sale_stock.
    def _compute_customer_lead(self):
        self.customer_lead = 0.0

    @api.depends("state", "locked")
    def _compute_product_uom_updatable(self):
        for line in self:
            # line.ids checks whether it's a new record not yet saved
            line.product_uom_updatable = (
                not line.ids or line.state == "draft" or not line.locked
            )

    @api.depends("order_id", "partner_id", "product_id")
    def _compute_display_name(self):
        name_per_id = self._additional_name_per_id()
        for so_line in self.sudo():
            if so_line.partner_id.lang:
                so_line = so_line.with_context(lang=so_line.order_id._get_lang())
            if (product := so_line.product_id).display_name:
                default_name = so_line._get_sale_order_line_multiline_description_sale()
                if so_line.name == default_name:
                    description = product.display_name
                else:
                    parts = (so_line.name or "").split("\n", 2)
                    description = (
                        parts[1]
                        if len(parts) > 1 and parts[1]
                        else product.display_name
                    )
            else:
                description = (so_line.name or "").split("\n", 1)[0]
            name = f"{so_line.order_id.name} - {description}"
            additional_name = name_per_id.get(so_line.id)
            if additional_name:
                name = f"{name} {additional_name}"
            so_line.display_name = name

    @api.depends("company_id", "product_id")
    def _compute_tax_ids(self):
        lines_by_company = defaultdict(lambda: self.env["sale.order.line"])
        cached_taxes = {}
        for line in self:
            if not line.product_id or line.product_type == "combo":
                line.tax_ids = False
                continue

            lines_by_company[line.company_id] += line

        for company, lines in lines_by_company.items():
            for line in lines.with_company(company):
                taxes = line.product_id.taxes_id._filter_taxes_by_company(company)
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
                # If company_id is set, always filter taxes by the company
                line.tax_ids = result

    @api.depends("partner_id", "product_id")
    def _compute_analytic_distribution(self):
        for line in self.filtered(lambda l: not l.display_type):
            distribution = line.env[
                "account.analytic.distribution.model"
            ]._get_distribution(
                {
                    "product_id": line.product_id.id,
                    "product_categ_id": line.product_id.categ_id.id,
                    "partner_id": line.order_id.partner_id.id,
                    "partner_category_id": line.order_id.partner_id.category_id.ids,
                    "company_id": line.company_id.id,
                }
            )
            line.analytic_distribution = distribution or line.analytic_distribution

    @api.depends("is_expense", "product_id")
    def _compute_qty_transfered_method(self):
        """Sale module compute delivered qty for product [('type', 'in', ['consu']), ('service_type', '=', 'manual')]
        -consu + expense_policy : analytic (sum of analytic unit_amount)
        -consu + no expense_policy : manual (set manually on SOL)
        -service (+ service_type='manual', the only available option) : manual

        This is true when only sale is installed: sale_stock redifine the behavior for 'consu' type,
        and sale_timesheet implements the behavior of 'service' + service_type=timesheet.
        """
        for line in self:
            if line.is_expense:
                line.qty_transfered_method = "analytic"
            elif line.product_id and line.product_type == "service":
                line.qty_transfered_method = "manual"
            elif line.product_id and line.product_type == "consu":
                line.qty_transfered_method = "stock_move"
            else:
                line.qty_transfered_method = False

    @api.depends("product_id")
    def _compute_translated_product_name(self):
        for line in self:
            line.translated_product_name = line.product_id.with_context(
                lang=line.order_id._get_lang(),
            ).display_name

    @api.depends("product_id")
    def _compute_product_template_id(self):
        for line in self:
            line.product_template_id = line.product_id.product_tmpl_id

    @api.depends("product_id")
    def _compute_is_product_archived(self):
        for line in self:
            line.is_product_archived = line.product_id and not line.product_id.active

    @api.depends("product_id")
    def _compute_custom_attribute_values(self):
        for line in self:
            if not line.product_id:
                line.product_custom_attribute_value_ids = False
                continue

            if not line.product_custom_attribute_value_ids:
                continue

            valid_values = (
                line.product_id.product_tmpl_id.valid_product_template_attribute_line_ids.product_template_value_ids
            )
            # remove the is_custom values that don't belong to this template
            for pacv in line.product_custom_attribute_value_ids:
                if pacv.custom_product_template_attribute_value_id not in valid_values:
                    line.product_custom_attribute_value_ids -= pacv

    @api.depends("product_id")
    def _compute_no_variant_attribute_values(self):
        for line in self:
            if not line.product_id:
                line.product_no_variant_attribute_value_ids = False
                continue

            if not line.product_no_variant_attribute_value_ids:
                continue

            valid_values = (
                line.product_id.product_tmpl_id.valid_product_template_attribute_line_ids.product_template_value_ids
            )
            # remove the no_variant attributes that don't belong to this template
            for ptav in line.product_no_variant_attribute_value_ids:
                if ptav._origin not in valid_values:
                    line.product_no_variant_attribute_value_ids -= ptav

    @api.depends("product_id", "product_id.uom_id", "product_id.uom_ids")
    def _compute_allowed_uom_ids(self):
        for line in self:
            line.allowed_uom_ids = line.product_id.uom_id | line.product_id.uom_ids

    @api.depends("product_id")
    def _compute_product_uom_id(self):
        for line in self:
            if not line.product_uom_id or (
                line.product_id.uom_id.id != line.product_uom_id.id
            ):
                line.product_uom_id = line.product_id.uom_id

    @api.depends("product_id", "linked_line_id", "linked_line_ids")
    def _compute_name(self):
        for line in self.filtered(lambda l: l.product_id or l.is_downpayment):
            lang = line.order_id._get_lang()
            if lang != self.env.lang:
                line = line.with_context(lang=lang)

            if line.product_id:
                line.name = line._get_sale_order_line_multiline_description_sale()
                continue

            if line.is_downpayment:
                line.name = line._get_downpayment_description()

    @api.depends("product_id")
    def _compute_product_uom_qty(self):
        for line in self:
            if line.product_id and not line.product_uom_qty:
                line.product_uom_qty = 1.0
            else:
                line.product_qty = False

    # order_id.pricelist_id is not included in api.depends due a botton in sale.order
    # that specifically recomputes prices whenever the user updates the pricelist in UI
    @api.depends("product_id", "product_uom_id", "product_uom_qty")
    def _compute_pricelist_item_id(self):
        for line in self:
            if (
                not line.product_id
                or line.display_type
                or not line.order_id.pricelist_id
            ):
                line.pricelist_item_id = False
            else:
                line.pricelist_item_id = line.order_id.pricelist_id._get_product_rule(
                    line.product_id,
                    quantity=line.product_uom_qty or 1.0,
                    uom=line.product_uom_id,
                    date=line._get_date_order(),
                )

    @api.depends("product_id", "product_uom_id", "product_uom_qty")
    def _compute_price_unit(self):
        for line in self:
            # Don't compute the price for deleted lines.
            if not line.order_id:
                continue

            # check if the price has been manually set or there is already invoiced amount.
            # if so, the price shouldn't change as it might have been manually edited.
            if (
                (
                    line.technical_price_unit != line.price_unit
                    and not line.env.context.get("force_price_recomputation")
                )
                or line.qty_invoiced > 0
                or (line.product_id.expense_policy == "cost" and line.is_expense)
            ):
                continue

            line = line.with_context(sale_write_from_compute=True)
            if not line.product_id or not line.product_uom_id:
                line.price_unit = False
                line.technical_price_unit = False
            else:
                line = line.with_company(line.company_id)
                price = line._get_price_display()
                line.price_unit = (
                    line.product_id._get_tax_included_unit_price_from_price(
                        price,
                        product_taxes=line.product_id.taxes_id.filtered(
                            lambda tax: tax.company_id == line.env.company
                        ),
                        fiscal_position=line.order_id.fiscal_position_id,
                    )
                )
                line.technical_price_unit = line.price_unit

    @api.depends("product_id", "product_uom_id", "product_uom_qty")
    def _compute_discount(self):
        discount_enabled = self.env[
            "product.pricelist.item"
        ]._is_discount_feature_enabled()
        for line in self:
            if (
                line.display_type
                or not line.product_id
                or not (line.order_id.pricelist_id and discount_enabled)
            ):
                line.discount = False
                continue

            line.discount = 0.0

            if not line.pricelist_item_id._show_discount():
                # No pricelist rule was found for the product
                # therefore, the pricelist didn't apply any discount/change
                # to the existing sales price.
                continue

            line = line.with_company(line.company_id)
            pricelist_price = line._get_pricelist_price()
            base_price = line._get_pricelist_price_before_discount()

            if base_price != 0:  # Avoid division by zero
                discount = (base_price - pricelist_price) / base_price * 100
                if (discount > 0 and base_price > 0) or (
                    discount < 0 and base_price < 0
                ):
                    # only show negative discounts if price is negative
                    # otherwise it's a surcharge which shouldn't be shown to the customer
                    line.discount = discount

    @api.depends("tax_ids", "product_uom_qty", "price_unit", "discount")
    def _compute_amounts(self):
        for line in self.filtered(lambda l: not l.display_type):
            base_line = line._prepare_base_line_for_taxes_computation()
            self.env["account.tax"]._add_tax_details_in_base_line(
                base_line, line.company_id
            )
            vals = {
                "price_subtotal": base_line["tax_details"][
                    "raw_total_excluded_currency"
                ],
                "price_total": base_line["tax_details"]["raw_total_included_currency"],
                "price_tax": (
                    base_line["tax_details"]["raw_total_included_currency"]
                    - base_line["tax_details"]["raw_total_excluded_currency"]
                ),
                "price_unit_discounted_taxexc": (
                    base_line["tax_details"]["raw_total_excluded_currency"]
                    / base_line["quantity"]
                    if base_line["quantity"]
                    else 0.0
                ),
                "price_unit_discounted_taxinc": (
                    base_line["tax_details"]["raw_total_included_currency"]
                    / base_line["quantity"]
                    if base_line["quantity"]
                    else 0.0
                ),
            }
            line.write(vals)

    @api.depends("qty_transfered_method")
    def _compute_qty_transfered(self):
        """This method compute the delivered quantity of the SO lines: it covers the case provide by sale module, aka
        expense/vendor bills (sum of unit_amount of AAL), and manual case.
        This method should be overridden to provide other way to automatically compute delivered qty. Overrides should
        take their concerned so lines, compute and set the `qty_transfered` field, and call super with the remaining
        records."""
        # compute for analytic lines
        lines_by_analytic = self.filtered(
            lambda sol: sol.qty_transfered_method == "analytic"
        )
        mapping = lines_by_analytic._get_qty_delivered_by_analytic(
            [("amount", "<=", 0.0)]
        )
        for so_line in lines_by_analytic:
            so_line.qty_transfered = mapping.get(so_line.id or so_line._origin.id, 0.0)

    @api.depends(
        "state",
        "product_uom_qty",
        "price_subtotal",
        "price_total",
        "qty_transfered",
        "invoice_line_ids.parent_state",
        "invoice_line_ids.product_uom_id",
        "invoice_line_ids.quantity",
    )
    def _compute_invoice_amounts(self):
        """Compute the quantity invoiced. If case of a refund, the quantity invoiced is decreased.
        Note that this is the case only if the refund is generated from the SO and that is intentional:
        if a refund made would automatically decrease the invoiced quantity,
        then there is a risk of reinvoicing it automatically, which may not be wanted at all.
        """
        combo_lines = set()
        for line in self.filtered(lambda l: not l.display_type):
            vals = {
                "qty_to_invoice": 0.0,
                "qty_invoiced": 0.0,
                "amount_to_invoice_taxinc": 0.0,
                "amount_to_invoice_taxexc": 0.0,
                "amount_invoiced_taxinc": 0.0,
                "amount_invoiced_taxexc": 0.0,
            }

            if line.state != "sale":
                line.write(vals)
                continue

            qty_policy = (
                line.product_uom_qty
                if line.product_id.invoice_policy == "order"
                else line.qty_transfered
            )
            vals.update(
                {
                    "qty_to_invoice": qty_policy,
                    "amount_to_invoice_taxinc": line.price_subtotal,
                    "amount_to_invoice_taxexc": line.price_total,
                }
            )

            if not line.invoice_line_ids:
                line.write(vals)
                continue

            for invoice_line in line._get_invoice_line_ids().filtered(
                lambda x: x.parent_state == "posted"
            ):
                invoice_date = invoice_line.move_id.invoice_date
                vals["qty_invoiced"] += (
                    invoice_line.product_uom_id._compute_quantity(
                        invoice_line.quantity, line.product_uom_id
                    )
                    * -invoice_line.move_id.direction_sign
                )
                vals["amount_invoiced_taxexc"] += (
                    invoice_line.currency_id._convert(
                        invoice_line.price_subtotal,
                        line.currency_id,
                        line.company_id,
                        invoice_date,
                    )
                    * -invoice_line.move_id.direction_sign
                )
                vals["amount_invoiced_taxinc"] += (
                    invoice_line.currency_id._convert(
                        invoice_line.price_total,
                        line.currency_id,
                        line.company_id,
                        invoice_date,
                    )
                    * -invoice_line.move_id.direction_sign
                )

            if (
                line.product_id.type == "combo"
                or line.combo_item_id
                and line.linked_line_id
            ):
                combo_lines.add(line.linked_line_id)
            else:
                vals["qty_to_invoice"] = max(
                    0, vals["qty_to_invoice"] - vals["qty_invoiced"]
                )
                vals["amount_to_invoice_taxexc"] = (
                    vals["qty_to_invoice"] * line.price_unit_discounted_taxexc
                )
                vals["amount_to_invoice_taxinc"] = (
                    vals["qty_to_invoice"] * line.price_unit_discounted_taxinc
                )

            line.write(vals)

        for combo_line in combo_lines:
            if any(
                line.combo_item_id and line.qty_to_invoice
                for line in combo_line.linked_line_ids
            ):
                combo_line.qty_to_invoice = (
                    combo_line.product_uom_qty - combo_line.qty_invoiced
                )
            else:
                combo_line.qty_to_invoice = 0.0

    @api.depends("state", "product_id", "qty_transfered", "qty_invoiced")
    def _compute_product_updatable(self):
        self.product_updatable = True
        for line in self:
            if (
                line.is_downpayment
                or line.state == "cancel"
                or line.state == "sale"
                and (
                    line.order_id.locked
                    or line.qty_transfered > 0
                    or line.qty_invoiced > 0
                )
            ):
                line.product_updatable = False

    @api.depends(
        "state",
        "product_uom_qty",
        "qty_invoiced",
        "qty_to_invoice",
        "amount_to_invoice_taxexc",
    )
    def _compute_invoice_state(self):
        """Compute the invoice status of a SO line. Possible statuses:
        - no: When the line is not confirmed or there are no ordered quantities.
        - to do: When the line is confirmed and nothing has been invoiced yet.
        - partially: When the line is confirmed and partially invoiced, but not fully.
        - done: When the line is confirmed and fully invoiced.
        - over done: In case of a product invoiced based on delivered quantities, when
          the line is confirmed and invoiced beyond its totality.
        - upselling: In case of a product invoiced based on ordered quantities for which
          we delivered more than expected. This status only applies in state 'sale'."""
        precision = self.env["decimal.precision"].precision_get("Product Unit")
        for line in self.filtered(lambda l: not l.display_type):
            # Default state: if the line is not in 'sale' state or has zero quantity
            if line.state != "sale":
                line.invoice_state = "no"
                continue

            # Handle upselling opportunity. This should have precedence since
            # it is not actually taking into account the invoiced quantity
            if (
                line.product_id.invoice_policy == "order"
                and float_compare(
                    line.qty_transfered,
                    line.product_uom_qty,
                    precision_digits=precision,
                )
                > 0
            ):
                line.invoice_state = "upselling"
                continue

            # Handle downpayments with nothing left to invoice
            if line.is_downpayment and line.amount_to_invoice_taxexc == 0:
                line.invoice_state = "done"
                continue

            # Check if there's still quantity to invoice
            if not float_is_zero(line.qty_to_invoice, precision_digits=precision):
                if float_is_zero(line.qty_invoiced, precision_digits=precision):
                    # Nothing invoiced yet
                    line.invoice_state = "to do"
                else:
                    # Some quantity already invoiced
                    line.invoice_state = "partially"
            # All quantity invoiced, check if equal to ordered or more
            elif float_is_zero(line.qty_to_invoice, precision_digits=precision):
                # Handle edge case when the line is updated to zero quantity
                # after being confirmed mainly due to customers repenting on
                # wanting the order or error done by the salesperson
                if float_is_zero(line.product_uom_qty, precision_digits=precision):
                    line.invoice_state = "done"
                    continue

                compare = float_compare(
                    line.qty_invoiced,
                    line.product_uom_qty,
                    precision_digits=precision,
                )
                if compare == 0:
                    line.invoice_state = "done"
                elif compare > 0:
                    line.invoice_state = "over done"
            else:
                line.invoice_state = "no"

    # ------------------------------------------------------------
    # ONCHANGE METHODS
    # ------------------------------------------------------------

    @api.onchange("product_id")
    def _onchange_product_id_warning(self):
        if not self.product_id:
            return

        warning = {}
        product = self.product_id
        if product.sale_line_warn != "no-message":
            warning["title"] = _(f"Warning for {product.name}")
            warning["message"] = product.sale_line_warn_msg

            if product.sale_line_warn == "block":
                self.product_id = False

            return {"warning": warning}

        return {}

    # ------------------------------------------------------------
    # SEARCH METHODS
    # ------------------------------------------------------------

    def _search_product_template_id(self, operator, value):
        return [("product_id.product_tmpl_id", operator, value)]

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    def _add_precomputed_values(self, vals_list):
        super()._add_precomputed_values(vals_list)
        for vals in vals_list:
            if "price_unit" in vals and "technical_price_unit" not in vals:
                vals["technical_price_unit"] = vals["price_unit"]

    def _additional_name_per_id(self):
        return {so_line.id: so_line._get_partner_display() for so_line in self}

    def compute_uom_qty(self, new_qty, stock_move, rounding=True):
        return self.product_uom_id._compute_quantity(
            new_qty, stock_move.product_uom, rounding
        )

    def _convert_to_sol_currency(self, amount, currency):
        """Convert the given amount from the given currency to the SO(L) currency.

        :param float amount: the amount to convert
        :param currency: currency in which the given amount is expressed
        :type currency: `res.currency` record
        :returns: converted amount
        :rtype: float"""
        self.ensure_one()
        to_currency = self.currency_id or self.order_id.currency_id
        if currency and to_currency and currency != to_currency:
            conversion_date = self.date_order or fields.Date.context_today(self)
            company = self.company_id or self.order_id.company_id or self.env.company
            return currency._convert(
                from_amount=amount,
                to_currency=to_currency,
                company=company,
                date=conversion_date,
                round=False,
            )

        return amount

    def _hook_on_created_confirmed_lines(self):
        """Hook method to be able to add custom logic when a line is created and confirmed"""
        # This method is called in create() after the lines are created
        # and before they are confirmed.
        # It is used to add custom logic for the lines that are created
        # and confirmed.
        if self.env.context.get("sale_no_log_for_new_lines"):
            pass

        for line in self:
            msg = _(f"Extra line with: {line.product_id.display_name}")
            line.order_id.message_post(body=msg)

    def _hook_on_written_confirmed_lines(self, write_vals, previous_vals):
        self._log_to_order_quantities_updated(write_vals, previous_vals)

    def _log_to_order_quantities_updated(self, write_vals, previous_vals):
        precision = self.env["decimal.precision"].precision_get("Product Unit")
        orders = self.mapped("order_id")
        for order in orders:
            order_lines = self.filtered(lambda l: l.order_id == order)
            order_qty_updated_msg = Markup("<b>%s</b><br/><ul>") % _(
                "The ordered quantities have been updated."
            )
            flag = False
            for line in order_lines:
                if (
                    "product_id" in write_vals
                    and write_vals["product_id"] != line.product_id.id
                ):
                    # tracking is meaningless if the product is changed as well.
                    continue

                line_flag = False
                line_qty_updated_msg = Markup(
                    f"<li>{line.product_id.display_name}:<br/>"
                )
                if (
                    "product_uom_qty" in write_vals
                    and float_compare(
                        previous_vals[line.id].get("product_uom_qty"),
                        line.product_uom_qty,
                        precision_digits=precision,
                    )
                    != 0
                ):
                    line_flag = True
                    line_qty_updated_msg += _(
                        f"-Ordered quantity: {previous_vals[line.id].get('product_uom_qty')} -> {line.product_uom_qty}"
                    ) + Markup("<br/>")

                    if line.product_id.type == "consu":
                        line_qty_updated_msg += _(
                            f"-Delivered quantity: {line.qty_transfered}"
                        ) + Markup("<br/>")

                    line_qty_updated_msg += _(
                        f"-Invoiced quantity: {line.qty_invoiced}"
                    ) + Markup("<br/>")
                line_qty_updated_msg += Markup("</li>")

                if line_flag:
                    order_qty_updated_msg += line_qty_updated_msg
                    flag = True

            order_qty_updated_msg += Markup("</ul>")
            if flag:
                order.message_post(body=order_qty_updated_msg)

    def _sanitize_create_display_type_vals(self, create_vals_list):
        """Sanitize the values to be used for creating a sale order line with display_type or technical_price_unit."""
        for vals in create_vals_list:
            if vals.get("display_type") or self.default_get(["display_type"]).get(
                "display_type"
            ):
                vals.update(
                    product_id=False,
                    product_uom_id=False,
                    product_uom_qty=False,
                    price_unit=False,
                )
            if "technical_price_unit" in vals and "price_unit" not in vals:
                # price_unit field was set as readonly in the view (but technical_price_unit not)
                # the field is not sent by the client and expected to be recomputed, but isn't
                # because technical_price_unit is set.
                vals.pop("technical_price_unit")

    def _sanitize_write_vals_technical_price_unit(self, write_vals):
        if (
            "technical_price_unit" in write_vals
            and "price_unit" not in write_vals
            and not self.env.context.get("sale_write_from_compute")
        ):
            # price_unit field was set as readonly in the view (but technical_price_unit not)
            # the field is not sent by the client and expected to be recomputed, but isn't
            # because technical_price_unit is set.
            write_vals.pop("technical_price_unit")

    def _validate_analytic_distribution(self):
        for line in self.filtered(lambda l: not l.display_type):
            line._validate_distribution(
                **{
                    "product": line.product_id.id,
                    "business_domain": "sale_order",
                    "company_id": line.company_id.id,
                }
            )

    def _get_custom_compute_tax_cache_key(self):
        """Hook method to be able to set/get cached taxes while computing them"""
        return tuple()

    def _get_date_order(self):
        self.ensure_one()
        return self.date_order

    def _get_date_planned(self):
        self.ensure_one()
        if self.state == "sale" and self.date_order:
            date_order = self.date_order
        else:
            date_order = fields.Datetime.now()
        return date_order + timedelta(days=self.customer_lead or 0.0)

    def _get_domain_sellable(self):
        discount_products_ids = self.env.companies.sale_discount_product_id.ids
        domain = [("is_downpayment", "=", False)]
        if discount_products_ids:
            domain = expression.AND(
                [
                    domain,
                    [("product_id", "not in", discount_products_ids)],
                ]
            )
        return domain

    def _get_downpayment_description(self):
        self.ensure_one()
        if self.display_type:
            return _("Down Payments")

        dp_state = self._get_downpayment_state()
        name = _("Down Payment")
        if dp_state == "draft":
            name = _(
                "Down Payment: %(date)s (Draft)",
                date=format_date(self.env, self.create_date.date()),
            )
        elif dp_state == "cancel":
            name = _("Down Payment (Cancelled)")
        else:
            invoice = (
                self._get_invoice_line_ids()
                .filtered(lambda aml: aml.quantity >= 0)
                .move_id.filtered(lambda move: move.move_type == "out_invoice")
            )
            if len(invoice) == 1 and invoice.payment_reference and invoice.invoice_date:
                name = _(
                    "Down Payment (ref: %(reference)s on %(date)s)",
                    reference=invoice.payment_reference,
                    date=format_date(self.env, invoice.invoice_date),
                )

        return name

    def _get_downpayment_line_price_unit(self, invoices):
        return sum(
            l.price_unit if l.move_id.move_type == "out_invoice" else -l.price_unit
            for l in self.invoice_line_ids
            if l.move_id.state == "posted"
            and l.move_id not in invoices  # don't recompute with the final invoice
        )

    def _get_downpayment_state(self):
        self.ensure_one()
        if self.display_type:
            return ""

        invoice_line_ids = self._get_invoice_line_ids()
        if all(line.parent_state == "draft" for line in invoice_line_ids):
            return "draft"
        if all(line.parent_state == "cancel" for line in invoice_line_ids):
            return "cancel"

        return ""

    def _get_invoice_line_ids(self):
        self.ensure_one()
        if self._context.get("accrual_entry_date"):
            return self.invoice_line_ids.filtered(
                lambda l: l.move_id.invoice_date
                and l.move_id.invoice_date <= self._context["accrual_entry_date"]
            )

        else:
            return self.invoice_line_ids

    def _get_invoice_line_sequence(self, new=0, old=0):
        """Method intended to be overridden in third-party module if we want to prevent the resequencing
        of invoice lines.

        :param int new:   the new line sequence
        :param int old:   the old line sequence

        :return:          the sequence of the SO line, by default the new one."""
        return new or old

    def _get_line_linked(self):
        """Return the linked line of this line, if any.

        This method relies on either `linked_line_id` or `linked_virtual_id` to retrieve the linked
        line, depending on whether the linked line is saved in the DB."""
        self.ensure_one()
        return (
            self.linked_line_id
            or (
                self.linked_virtual_id
                and self.order_id.line_ids.filtered(
                    lambda line: line.virtual_id == self.linked_virtual_id
                ).ensure_one()
            )
            or self.env["sale.order.line"]
        )

    def _get_lines_linked(self):
        """Return the linked lines of this line, if any.

        This method relies on either `linked_line_id` or `linked_virtual_id` to retrieve the linked
        lines, depending on whether this line is saved in the DB.

        Note: we can't rely on `linked_line_ids` as it will only be populated when both this line
        and its linked lines are saved in the DB, which we can't ensure."""
        self.ensure_one()
        return (
            (
                self._origin
                and self.order_id.line_ids.filtered(
                    lambda line: line.linked_line_id._origin == self._origin
                )
            )
            or (
                self.virtual_id
                and self.order_id.line_ids.filtered(
                    lambda line: line.linked_virtual_id == self.virtual_id
                )
            )
            or self.env["sale.order.line"]
        )

    def _get_lines_with_price(self):
        """A combo product line always has a zero price (by design). The actual price of the combo
        product can be computed by summing the prices of its combo items (i.e. its linked lines).
        """
        return self.linked_line_ids if self.product_type == "combo" else self

    def _get_partner_display(self):
        self.ensure_one()
        commercial_partner = self.sudo().partner_id.commercial_partner_id
        return f"({commercial_partner.ref or commercial_partner.name})"

    def _get_price_display(self):
        """Compute the displayed unit price for a given line.

        Overridden in custom flows:
        * where the price is not specified by the pricelist
        * where the discount is not specified by the pricelist

        Note: self.ensure_one()"""
        self.ensure_one()

        if self.product_type == "combo":
            return 0  # The display price of a combo line should always be 0.

        if self.combo_item_id:
            return self._get_price_display_combo_item()

        return self._get_price_display_ignore_combo()

    def _get_price_display_combo_item(self):
        """Compute the display price of this SOL's combo item.

        A combo item's price is a fraction of its combo product's price (i.e. the product of type
        `combo` which is referenced in this SOL's linked line). It is independent of the combo
        item's product (i.e. the product referenced in this SOL). The combo's `base_price` will be
        used to prorate the price of this combo with respect to the other combos in the combo
        product.

        Note: this method will throw if this SOL has no combo item or no linked combo product.
        """
        self.ensure_one()
        # Compute the combo product's price.
        combo_line = self._get_line_linked()
        combo_product_price = combo_line._get_price_display_ignore_combo()
        # Compute the combos' base prices.
        combo_base_prices = {
            combo_id: combo_id.currency_id._convert(
                from_amount=combo_id.base_price,
                to_currency=self.currency_id,
                company=self.company_id,
                date=self.order_id.date_order,
            )
            for combo_id in combo_line.product_template_id.combo_ids
        }
        total_combo_base_price = sum(combo_base_prices.values())
        # Compute the prorated combo prices.
        combo_prices = {
            combo_id: self.currency_id.round(
                # Don't divide by total_combo_base_price if it's 0. This will make the prorating
                # wrong, but the delta will be fixed by combo_price_delta below.
                base_price
                * combo_product_price
                / (total_combo_base_price or 1)
            )
            for (combo_id, base_price) in combo_base_prices.items()
        }
        # Compute the delta between the combo product's price and the sum of its combo prices.
        # Ideally, this should be 0, but division in python isn't perfect, so we may need to adjust
        # the combo prices to make the delta 0.
        combo_price_delta = combo_product_price - sum(combo_prices.values())
        if combo_price_delta:
            combo_prices[
                combo_line.product_template_id.combo_ids[-1]
            ] += combo_price_delta
        # Add the extra price of this combo item, as well as the extra prices of any `no_variant`
        # attributes to the combo price.
        return (
            combo_prices[self.combo_item_id.combo_id]
            + self.combo_item_id.extra_price
            + self.product_id._get_no_variant_attributes_price_extra(
                self.product_no_variant_attribute_value_ids
            )
        )

    def _get_price_display_ignore_combo(self):
        """This helper method allows to compute the display price of a SOL, while ignoring combo
        logic.

        I.e. this method returns the display price of a SOL as if it were neither a combo line nor a
        combo item line."""
        self.ensure_one()
        pricelist_price = self._get_pricelist_price()

        if not self.pricelist_item_id._show_discount():
            # No pricelist rule found => no discount from pricelist
            return pricelist_price

        base_price = self._get_pricelist_price_before_discount()

        # negative discounts (= surcharge) are included in the display price
        return max(base_price, pricelist_price)

    def _get_pricelist_price(self):
        """Compute the price given by the pricelist for the given line information.

        :return: the product sales price in the order currency (without taxes)
        :rtype: float"""
        self.ensure_one()
        self.product_id.ensure_one()
        return self.pricelist_item_id._compute_price(
            product=self.product_id.with_context(**self._get_product_price_context()),
            quantity=self.product_uom_qty or 1.0,
            uom=self.product_uom_id,
            date=self._get_date_order(),
            currency=self.currency_id,
        )

    def _get_pricelist_price_before_discount(self):
        """Compute the price used as base for the pricelist price computation.
        :return: the product sales price in the order currency (without taxes)
        :rtype: float"""
        self.ensure_one()
        self.product_id.ensure_one()
        return self.pricelist_item_id._compute_price_before_discount(
            product=self.product_id.with_context(**self._get_product_price_context()),
            quantity=self.product_uom_qty or 1.0,
            uom=self.product_uom_id,
            date=self.order_id.date_order,
            currency=self.currency_id,
        )

    def _get_pricelist_price_context(self):
        """DO NOT USE in new code, this contextual logic should be dropped or heavily refactored soon"""
        self.ensure_one()
        return {
            "pricelist": self.order_id.pricelist_id.id,
            "uom": self.product_uom_id.id,
            "quantity": self.product_uom_qty,
            "date": self._get_date_order(),
        }

    def _get_product_price_context(self):
        """Gives the context for product price computation.

        :return: additional context to consider extra prices from attributes in the base product price.
        :rtype: dict"""
        self.ensure_one()
        return self.product_id._get_product_price_context(
            self.product_no_variant_attribute_value_ids,
        )

    def _get_protected_fields(self):
        """Give the fields that should not be modified on a locked SO.

        :returns: list of field names
        :rtype: list"""
        return [
            "product_id",
            "name",
            "price_unit",
            "product_uom_id",
            "product_uom_qty",
            "tax_ids",
            "analytic_distribution",
            "discount",
        ]

    def _get_qty_delivered_by_analytic(self, additional_domain):
        """Compute and write the delivered quantity of current SO lines, based on their related
        analytic lines.
        :param additional_domain: domain to restrict AAL to include in computation (required since timesheet is an AAL with a project ...)
        """
        result = defaultdict(float)

        # avoid recomputation if no SO lines concerned
        if not self:
            return result

        # group analytic lines by product uom and so line
        domain = expression.AND([[("so_line", "in", self.ids)], additional_domain])
        data = self.env["account.analytic.line"]._read_group(
            domain,
            ["product_uom_id", "so_line"],
            ["unit_amount:sum", "move_line_id:count_distinct", "__count"],
        )

        # convert uom and sum all unit_amount of analytic lines to get the delivered qty of SO lines
        for uom, so_line, unit_amount_sum, move_line_id_count_distinct, count in data:
            if not uom:
                continue

            # avoid counting unit_amount twice when dealing with multiple analytic lines on the same move line
            if move_line_id_count_distinct == 1 and count > 1:
                qty = unit_amount_sum / count
            else:
                qty = unit_amount_sum
            qty = uom._compute_quantity(
                qty, so_line.product_uom_id, rounding_method="HALF-UP"
            )
            result[so_line.id] += qty

        return result

    def _get_sale_order_line_multiline_description_sale(self):
        """Compute a default multiline description for this sales order line.

        In most cases the product description is enough but sometimes we need to append information that only
        exists on the sale order line itself.
        e.g:
        - custom attributes and attributes that don't create variants, both introduced by the "product configurator"
        - in event_sale we need to know specifically the sales order line as well as the product to generate the name:
          the product is not sufficient because we also need to know the event_id and the event_ticket_id (both which belong to the sale order line).
        """
        self.ensure_one()
        description = (
            self.product_id.get_product_multiline_description_sale()
            + self._get_sale_order_line_multiline_description_variants()
        )
        if self.linked_line_id and not self.combo_item_id:
            description += "\n" + _(
                "Option for: %s", self.linked_line_id.product_id.display_name
            )
        if self.linked_line_ids and self.product_type != "combo":
            description += "\n" + "\n".join(
                [
                    _("Option: %s", linked_line.product_id.display_name)
                    for linked_line in self.linked_line_ids
                ]
            )
        return description

    def _get_sale_order_line_multiline_description_variants(self):
        """When using no_variant attributes or is_custom values, the product
        itself is not sufficient to create the description: we need to add
        information about those special attributes and values.

        :return: the description related to special variant attributes/values
        :rtype: string"""
        no_variant_ptavs = self.product_no_variant_attribute_value_ids._origin.filtered(
            # Only describe the attributes where a choice was made by the customer
            lambda ptav: ptav.display_type == "multi"
            or ptav.attribute_line_id.value_count > 1
        )
        if not self.product_custom_attribute_value_ids and not no_variant_ptavs:
            return ""

        name = "\n"
        custom_ptavs = (
            self.product_custom_attribute_value_ids.custom_product_template_attribute_value_id
        )
        multi_ptavs = no_variant_ptavs.filtered(
            lambda ptav: ptav.display_type == "multi"
        ).sorted()

        # display the no_variant attributes, except those that are also
        # displayed by a custom (avoid duplicate description)
        for ptav in no_variant_ptavs - multi_ptavs - custom_ptavs:
            name += "\n" + ptav.display_name

        # display the selected values per attribute on a single for a multi checkbox
        for pta, ptavs in groupby(multi_ptavs, lambda ptav: ptav.attribute_id):
            name += "\n" + _(
                "%(attribute)s: %(values)s",
                attribute=pta.name,
                values=", ".join(ptav.name for ptav in ptavs),
            )

        # Sort the values according to _order settings, because it doesn't work for virtual records in onchange
        sorted_custom_ptav = (
            self.product_custom_attribute_value_ids.custom_product_template_attribute_value_id.sorted()
        )
        for patv in sorted_custom_ptav:
            pacv = self.product_custom_attribute_value_ids.filtered(
                lambda pcav: pcav.custom_product_template_attribute_value_id == patv
            )
            name += "\n" + pacv.display_name

        return name

    def _prepare_aml_vals(self, **optional_values):
        """Prepare the values to create an invoice line from a sale order line.
        :param optional_values: any parameter that should be added to the returned invoice line
        :rtype: dict"""
        self.ensure_one()

        if self.product_id.type == "combo":
            # If the quantity to invoice is a whole number, format it as an integer (with no decimal point)
            qty_to_invoice = (
                int(self.qty_to_invoice)
                if self.qty_to_invoice == int(self.qty_to_invoice)
                else self.qty_to_invoice
            )
            return {
                "display_type": "line_section",
                "sequence": self.sequence,
                "name": f"{self.product_id.name} x {qty_to_invoice}",
                "product_uom_id": self.product_uom_id.id,
                "quantity": self.qty_to_invoice,
                "sale_line_ids": [Command.link(self.id)],
                **optional_values,
            }

        res = {
            "display_type": self.display_type or "product",
            "sequence": self.sequence,
            "product_id": self.product_id.id,
            "product_uom_id": self.product_uom_id.id,
            "quantity": self.qty_to_invoice,
            "name": self.env["account.move.line"]._get_journal_items_full_name(
                self.name, self.product_id.display_name
            ),
            "price_unit": self.price_unit,
            "discount": self.discount,
            "tax_ids": [Command.set(self.tax_ids.ids)],
            "sale_line_ids": [Command.link(self.id)],
            "is_downpayment": self.is_downpayment,
        }
        downpayment_lines = self.invoice_line_ids.filtered("is_downpayment")
        if self.is_downpayment and downpayment_lines:
            res["account_id"] = downpayment_lines.account_id[:1].id
        if optional_values:
            res.update(optional_values)
        if self.display_type:
            res["account_id"] = False
        return res

    def _prepare_base_line_for_taxes_computation(self, **kwargs):
        """Convert the current record to a dictionary in order to use
        the generic taxes computation method defined on account.tax.

        :return: A python dictionary."""
        self.ensure_one()
        return self.env["account.tax"]._prepare_base_line_for_taxes_computation(
            self,
            **{
                "tax_ids": self.tax_ids,
                "quantity": self.product_uom_qty,
                "partner_id": self.order_id.partner_id,
                "currency_id": self.order_id.currency_id
                or self.order_id.company_id.currency_id,
                "rate": self.order_id.currency_rate,
                **kwargs,
            },
        )

    def _prepare_procurement_values(self, group_id=False):
        """Prepare specific key for moves or other components that will be created from a stock rule
        coming from a sale order line. This method could be override in order to add other custom key that could
        be used in move/po creation."""
        return {}

    def _prepare_write_previous_vals(self, write_vals):
        """Prepare the old values of the fields that are going to be written.
        This is used to check if the values have changed and to trigger the
        corresponding actions."""
        previous_vals = {}
        for line in self:
            if "product_uom_qty" in write_vals:
                previous_vals[line.id] = {"product_uom_qty": line.product_uom_qty}
            if "qty_transfered" in write_vals:
                previous_vals[line.id] = {"qty_transfered": line.qty_transfered}
            if "qty_invoiced" in write_vals:
                previous_vals[line.id] = {"qty_invoiced": line.qty_invoiced}
        return previous_vals

    # ------------------------------------------------------------
    # PRODUCT CATALOG MIXIN
    # ------------------------------------------------------------

    # ------------------------------------------------------------
    # VALIDATIONS
    # ------------------------------------------------------------

    def _can_be_invoiced_alone(self):
        """Whether a given line is meaningful to invoice alone.

        It is generally meaningless/confusing or even wrong to invoice some specific SOlines
        (delivery, discounts, rewards, ...) without others, unless they are the only left to invoice
        in the SO."""
        self.ensure_one()
        return self.product_id.id != self.company_id.sale_discount_product_id.id

    def _cant_be_unlinked(self):
        """Check whether given lines can be deleted or not.

        * Lines cannot be deleted if the order is confirmed.
        * Down payment lines who have not yet been invoiced bypass that exception.
        * Sections and Notes can always be deleted.

        :returns: Sales Order Lines that cannot be deleted
        :rtype: `sale.order.line` recordset"""
        return self.filtered(
            lambda line: line.state == "sale"
            and (line.invoice_line_ids or not line.is_downpayment)
            and not line.display_type
        )

    def _check_write_display_type(self, write_vals):
        if "display_type" in write_vals:
            lines = self.filtered(
                lambda l: l.display_type != write_vals.get("display_type")
            )
            if lines:
                raise UserError(
                    _(
                        "You cannot change the type of a purchase order line. Instead you should "
                        "delete the current line and create a new line of the proper type."
                    )
                )

    def _check_write_product_updatable(self, write_vals):
        if "product_id" in write_vals:
            lines = self.filtered(
                lambda l: l.product_id.id != write_vals["product_id"]
                and not l.product_updatable
            )
            if lines:
                raise UserError(_("You cannot modify the product of this order line."))

    def _check_write_protected_fields(self, write_vals):
        # Prevent writing on a locked SO.
        protected_fields = self._get_protected_fields()
        if any(self.order_id.mapped("locked")) and any(
            f in write_vals.keys() for f in protected_fields
        ):
            protected_fields_modified = list(
                set(protected_fields) & set(write_vals.keys())
            )

            if "name" in protected_fields_modified and all(
                self.mapped("is_downpayment")
            ):
                protected_fields_modified.remove("name")

            fields = (
                self.env["ir.model.fields"]
                .sudo()
                .search(
                    [
                        ("name", "in", protected_fields_modified),
                        ("model", "=", self._name),
                    ]
                )
            )
            if fields:
                raise UserError(
                    _(
                        "It is forbidden to modify the following fields in a locked order:\n%s",
                        "\n".join(fields.mapped("field_description")),
                    )
                )

    def _has_valued_move_ids(self):
        return self.move_ids

    def _is_delivery(self):
        self.ensure_one()
        return False

    def _is_not_sellable_line(self):
        # True if the line is a computed line (reward, delivery, ...) that user cannot add manually
        return False
