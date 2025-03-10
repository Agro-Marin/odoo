from collections import defaultdict
from datetime import datetime, time
from dateutil.relativedelta import relativedelta
from pytz import UTC

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT, get_lang
from odoo.tools.float_utils import float_compare, float_round, float_is_zero
from odoo.tools.translate import _


class PurchaseOrderLine(models.Model):
    """Inherit PurchaseOrderLine"""

    _name = "purchase.order.line"
    _inherit = ["analytic.mixin"]
    _description = "Purchase Order Line"
    _check_company_auto = True
    _order = "order_id, sequence, id"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    order_id = fields.Many2one(
        comodel_name="purchase.order",
        string="Order Reference",
        required=True,
        auto_join=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        related="order_id.company_id",
        store=True,
        string="Company",
        precompute=True,
        readonly=True,
        index=True,
    )
    currency_id = fields.Many2one(
        related="order_id.currency_id",
        store=True,
        string="Currency",
        depends=["order_id.currency_id"],
        precompute=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        related="order_id.partner_id",
        store=True,
        string="Partner",
        precompute=True,
        readonly=True,
        index=True,
    )
    user_id = fields.Many2one(
        related="order_id.user_id",
        store=True,
        string="Buyer",
        precompute=True,
        readonly=True,
    )
    date_order = fields.Datetime(
        related="order_id.date_order",
        store=True,
        string="Order Date",
        precompute=True,
        readonly=True,
        index=True,
    )
    state = fields.Selection(
        related="order_id.state",
        store=True,
        string="Order Status",
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
        help="Technical field for UX purpose.",
    )

    is_downpayment = fields.Boolean()
    is_expense = fields.Boolean(
        string="Is expense",
        help="Is true if the sales order line comes from an expense or a vendor bills",
    )

    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        change_default=True,
        domain=[("purchase_ok", "=", True)],
        ondelete="restrict",
        index="btree_not_null",
    )
    product_type = fields.Selection(
        related="product_id.type",
        depends=["product_id"],
        readonly=True,
    )
    product_template_attribute_value_ids = fields.Many2many(
        related="product_id.product_template_attribute_value_ids",
        readonly=True,
    )
    product_no_variant_attribute_value_ids = fields.Many2many(
        comodel_name="product.template.attribute.value",
        string="Product attribute values that do not create variants",
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
        domain="[('id', 'in', allowed_uom_ids)]",
        ondelete="restrict",
    )
    product_qty = fields.Float(
        string="Quantity",
        digits="Product Unit",
        compute="_compute_product_qty",
        store=True,
        precompute=True,
        readonly=False,
    )
    product_uom_qty = fields.Float(
        string="Quantity UoM",
        digits="Product Unit",
        compute="_compute_product_uom_qty",
        store=True,
        precompute=True,
        readonly=True,
    )
    name = fields.Text(
        string="Description",
        required=True,
        compute="_compute_name_price_unit_discount_date_planned",
        store=True,
        precompute=True,
        readonly=False,
    )
    price_unit = fields.Float(
        string="Unit Price",
        digits="Product Price",
        compute="_compute_name_price_unit_discount_date_planned",
        store=True,
        precompute=True,
        readonly=False,
        aggregator="avg",
    )
    discount = fields.Float(
        string="Discount (%)",
        digits="Discount",
        compute="_compute_name_price_unit_discount_date_planned",
        store=True,
        precompute=True,
        readonly=False,
    )
    date_planned = fields.Datetime(
        string="Expected Arrival",
        compute="_compute_name_price_unit_discount_date_planned",
        store=True,
        precompute=True,
        readonly=False,
        index=True,
        help="Delivery date expected from vendor. This date respectively "
        "defaults to vendor pricelist lead time then today's date.",
    )
    price_subtotal = fields.Monetary(
        string="Subtotal",
        compute="_compute_amounts",
        store=True,
        precompute=True,
    )
    price_tax = fields.Monetary(
        string="Tax",
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
        relation="account_move_line_purchase_order_line_rel",
        column1="order_line_id",
        column2="move_line_id",
        string="Bill Lines",
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
    invoice_state = fields.Selection(
        selection=[
            ("no", "Nothing to bill"),
            ("to do", "To bill"),
            ("partially", "Partially billed"),
            ("done", "Fully billed"),
            ("over done", "Over billed"),
        ],
        string="Invoice status",
        default="no",
        compute="_compute_invoice_state",
        store=True,
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
                AND date_planned IS NOT NULL
            )
        )""",
        "Missing required fields on accountable purchase order line.",
    )
    _non_accountable_null_fields = models.Constraint(
        """CHECK(
            display_type IS NULL
            OR (
                product_id IS NULL
                AND product_uom_id IS NULL
                AND product_uom_qty = 0
                AND price_unit = 0
                AND date_planned is NULL
            )
        )""",
        "Forbidden values on non-accountable purchase order line",
    )

    # -------------------------------------------------------------------------
    # CRUD METHODS
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        self._sanitize_create_display_type_vals(vals_list)

        res = super().create(vals_list)

        lines_confirmed = res.filtered(
            lambda l: l.state == "purchase" and not l.display_type
        )
        lines_confirmed._hook_on_created_confirmed_lines()

        return res

    def write(self, vals):
        self._check_write_display_type(vals)

        previous_vals = self._prepare_write_previous_vals(vals)

        res = super().write(vals)

        confirmed_lines = self.filtered(
            lambda l: l.state == "purchase" and not l.display_type
        )
        confirmed_lines._hook_on_written_confirmed_lines(vals, previous_vals)

        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_confirmed(self):
        if self._cant_be_unlinked():
            raise UserError(
                _(
                    'Cannot delete a purchase order line which is in state "Confirmed".',
                )
            )

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------

    @api.depends("state", "locked")
    def _compute_product_uom_updatable(self):
        for line in self:
            # line.ids checks whether it's a new record not yet saved
            line.product_uom_updatable = (
                not line.ids or line.state == "draft" or not line.locked
            )

    @api.depends("company_id", "product_id")
    def _compute_tax_ids(self):
        lines_by_company = defaultdict(lambda: self.env["purchase.order.line"])
        cached_taxes = {}
        for line in self.filtered(lambda l: not l.display_type):
            if not line.product_id:
                line.tax_ids = False
                continue

            lines_by_company[line.company_id] += line

        for company, lines in lines_by_company.items():
            for line in lines.with_company(company):
                taxes = line.product_id.supplier_taxes_id._filter_taxes_by_company(
                    company
                )
                if not taxes:
                    line.tax_ids = False
                    continue

                fiscal_position = line.order_id.fiscal_position_id
                cache_key = (fiscal_position.id, company.id, tuple(taxes.ids))
                if cache_key in cached_taxes:
                    result = cached_taxes[cache_key]
                else:
                    result = fiscal_position.map_tax(taxes)
                    cached_taxes[cache_key] = result
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
        for line in self:
            if line.is_expense:
                line.qty_transfered_method = "analytic"
            elif line.product_id and line.product_type == "service":
                line.qty_transfered_method = "manual"
            elif line.product_id and line.product_type == "consu":
                line.qty_transfered_method = "stock_move"
            else:
                line.qty_transfered_method = False

    @api.depends(
        "product_id",
        "product_id.uom_id",
        "product_id.uom_ids",
        "product_id.seller_ids",
        "product_id.seller_ids.product_uom_id",
    )
    def _compute_allowed_uom_ids(self):
        for line in self:
            line.allowed_uom_ids = (
                line.product_id.uom_id
                | line.product_id.uom_ids
                | line.product_id.seller_ids.product_uom_id
            )

    @api.depends("product_id")
    def _compute_product_uom_id(self):
        for line in self:
            if not line.product_uom_id and line.product_id:
                line.product_uom_id = line.product_id.uom_id

    @api.depends("product_id", "product_uom_id")
    def _compute_product_qty(self):
        for line in self:
            if line.product_id:
                line._get_compute_product_qty()
            else:
                line.product_qty = False

    @api.depends("product_id", "product_id.uom_id", "product_uom_id", "product_qty")
    def _compute_product_uom_qty(self):
        for line in self:
            if line.product_id and line.product_id.uom_id != line.product_uom_id:
                line.product_uom_qty = line.product_uom_id._compute_quantity(
                    line.product_qty, line.product_id.uom_id
                )
            else:
                line.product_uom_qty = line.product_qty

    @api.depends("company_id", "partner_id", "product_uom_id", "product_qty")
    def _compute_name_price_unit_discount_date_planned(self):
        for line in self:
            if (
                not line.company_id
                or not line.product_id
                or line.invoice_line_ids
                or self.env.context.get("skip_uom_conversion")
            ):
                continue

            params = line._get_select_sellers_params()
            seller = line.product_id._select_seller(
                partner_id=line.partner_id,
                quantity=line.product_qty,
                date=line.order_id.date_order
                and line.order_id.date_order.date()
                or fields.Date.context_today(line),
                uom_id=line.product_uom_id,
                params=params,
            )

            # If not seller, use the standard price. It needs a proper currency conversion.
            if not seller:
                line.discount = 0
                unavailable_seller = line.product_id.seller_ids.filtered(
                    lambda s: s.partner_id == line.order_id.partner_id
                )
                if (
                    not unavailable_seller
                    and line.price_unit
                    and line.product_uom_id == line._origin.product_uom_id
                ):
                    # Avoid to modify the price unit if there is no price list for this partner and
                    # the line has already one to avoid to override unit price set manually.
                    continue

                po_line_uom = line.product_uom_id or line.product_id.uom_id
                price_unit = line.env["account.tax"]._fix_tax_included_price_company(
                    line.product_id.uom_id._compute_price(
                        line.product_id.standard_price, po_line_uom
                    ),
                    line.product_id.supplier_taxes_id,
                    line.tax_ids,
                    line.company_id,
                )
                price_unit = line.product_id.cost_currency_id._convert(
                    price_unit,
                    line.currency_id,
                    line.company_id,
                    line.date_order or fields.Date.context_today(line),
                    False,
                )
                line.price_unit = float_round(
                    price_unit,
                    precision_digits=max(
                        line.currency_id.decimal_places,
                        self.env["decimal.precision"].precision_get("Product Price"),
                    ),
                )
            elif seller:
                price_unit = line.env["account.tax"]._fix_tax_included_price_company(
                    seller.price,
                    line.product_id.supplier_taxes_id,
                    line.tax_ids,
                    line.company_id,
                )
                price_unit = seller.currency_id._convert(
                    price_unit,
                    line.currency_id,
                    line.company_id,
                    line.date_order or fields.Date.context_today(line),
                    False,
                )
                price_unit = float_round(
                    price_unit,
                    precision_digits=max(
                        line.currency_id.decimal_places,
                        self.env["decimal.precision"].precision_get("Product Price"),
                    ),
                )
                line.price_unit = (
                    seller.product_uom_id or seller.product_tmpl_id.uom_id
                )._compute_price(price_unit, line.product_uom_id)
                line.discount = seller.discount or 0.0

            if not line.date_planned:
                line.date_planned = line._get_date_planned(seller).strftime(
                    DEFAULT_SERVER_DATETIME_FORMAT
                )

            line._get_compute_name(seller, params)

    @api.depends("tax_ids", "product_qty", "price_unit", "discount")
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
        for line in self:
            if line.qty_transfered_method == "manual":
                line.qty_transfered = 0.0
            else:
                line.qty_transfered = False

    @api.depends(
        "state",
        "product_uom_qty",
        "qty_transfered",
        "invoice_line_ids.parent_state",
        "invoice_line_ids.quantity",
    )
    def _compute_invoice_amounts(self):
        for line in self.filtered(lambda l: not l.display_type):
            vals = {
                "qty_invoiced": 0.0,
                "qty_to_invoice": 0.0,
            }

            if line.state != "purchase":
                line.write(vals)
                continue

            qty_done = (
                line.product_qty
                if line.product_id.bill_policy == "purchase"
                else line.qty_transfered
            )
            vals.update(
                {
                    "qty_to_invoice": qty_done,
                }
            )

            if not line.invoice_line_ids:
                line.write(vals)
                continue

            for invoice_line in line._get_invoice_line_ids().filtered(
                lambda x: x.parent_state == "posted"
            ):
                vals["qty_invoiced"] += (
                    invoice_line.product_uom_id._compute_quantity(
                        invoice_line.quantity, line.product_uom_id
                    )
                    * invoice_line.move_id.direction_sign
                )

            vals["qty_to_invoice"] = max(
                0, vals["qty_to_invoice"] - vals["qty_invoiced"]
            )
            line.write(vals)

    @api.depends("state", "product_uom_qty", "qty_invoiced", "qty_to_invoice")
    def _compute_invoice_state(self):
        precision = self.env["decimal.precision"].precision_get("Product Unit")
        for line in self.filtered(lambda l: not l.display_type):
            if line.state != "purchase" or float_is_zero(
                line.product_qty, precision_digits=precision
            ):
                line.invoice_state = "no"
                continue

            if not float_is_zero(line.qty_to_invoice, precision_digits=precision):
                if float_is_zero(line.qty_invoiced, precision_digits=precision):
                    line.invoice_state = "to do"
                elif not float_is_zero(line.qty_invoiced, precision_digits=precision):
                    line.invoice_state = "partially"
            elif float_is_zero(line.qty_to_invoice, precision_digits=precision):
                compare = float_compare(
                    line.qty_invoiced, line.product_qty, precision_digits=precision
                )
                if compare == 0:
                    line.invoice_state = "done"
                elif compare > 0:
                    line.invoice_state = "over done"
            else:
                line.invoice_state = "no"

    @api.depends("state", "product_id", "qty_transfered", "qty_invoiced")
    def _compute_product_updatable(self):
        self.product_updatable = True
        for line in self:
            if (
                line.state == "cancel"
                or line.state == "purchase"
                and (
                    line.order_id.locked
                    or line.qty_invoiced > 0
                    or line.qty_transfered > 0
                )
            ):
                line.product_updatable = False

    # -------------------------------------------------------------------------
    # ONCHANGE METHODS
    # -------------------------------------------------------------------------

    @api.onchange("product_id")
    def onchange_product_id_warning(self):
        if not self.product_id or not self.env.user.has_group(
            "purchase.group_warning_purchase"
        ):
            return

        warning = {}
        product = self.product_id
        if product.purchase_line_warn != "no-message":
            warning["title"] = _(f"Warning for {product.name}")
            warning["message"] = product.purchase_line_warn_msg

            if product.purchase_line_warn == "block":
                self.product_id = False

            return {"warning": warning}

        return {}

    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------

    def action_open_order(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "purchase.order",
            "view_mode": "form",
            "res_id": self.order_id.id,
        }

    # ------------------------------------------------------------
    # CATALOGUE MIXIN
    # ------------------------------------------------------------

    def action_add_from_catalog(self):
        order = self.env["purchase.order"].browse(self.env.context.get("order_id"))
        return order.with_context(
            child_field="line_ids"
        ).action_add_from_catalog()

    def _get_product_catalog_lines_data(self, **kwargs):
        """Return information about purchase order lines in `self`.

        If `self` is empty, this method returns only the default value(s) needed for the product
        catalog. In this case, the quantity that equals 0.

        Otherwise, it returns a quantity and a price based on the product of the POL(s) and whether
        the product is read-only or not.

        A product is considered read-only if the order is considered read-only (see
        ``PurchaseOrder._is_readonly`` for more details) or if `self` contains multiple records
        or if it has purchase_line_warn == "block".

        Note: This method cannot be called with multiple records that have different products linked.

        :raise odoo.exceptions.ValueError: ``len(self.product_id) != 1``
        :rtype: dict
        :return: A dict with the following structure:
            {
                "quantity": float,
                "price": float,
                "readOnly": bool,
                "uom": dict,
                "purchase_uom": dict,
                "packaging": dict,
                "warning": String,
            }"""
        if len(self) == 1:
            catalog_info = self.order_id._get_product_price_and_data(self.product_id)
            uom = {
                "display_name": self.product_id.uom_id.display_name,
                "id": self.product_id.uom_id.id,
            }
            catalog_info.update(
                quantity=self.product_qty,
                price=self.price_unit * (1 - self.discount / 100),
                readOnly=self.order_id._is_readonly(),
                uom=uom,
            )
            if self.product_id.uom_id != self.product_uom_id:
                catalog_info["purchase_uom"] = {
                    "display_name": self.product_uom_id.display_name,
                    "id": self.product_uom_id.id,
                }
            return catalog_info

        elif self:
            self.product_id.ensure_one()
            order_line = self[0]
            catalog_info = order_line.order_id._get_product_price_and_data(
                order_line.product_id
            )
            catalog_info["quantity"] = sum(
                self.mapped(
                    lambda line: line.product_uom_id._compute_quantity(
                        qty=line.product_qty,
                        to_unit=line.product_id.uom_id,
                    )
                )
            )
            catalog_info["readOnly"] = True
            return catalog_info

        return {"quantity": 0}

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------

    def _convert_to_middle_of_day(self, date):
        """Return a datetime which is the noon of the input date(time) according
        to order user's time zone, convert to UTC time."""
        return (
            self.order_id.get_timezone()
            .localize(datetime.combine(date, time(12)))
            .astimezone(UTC)
            .replace(tzinfo=None)
        )

    def _hook_on_created_confirmed_lines(self):
        for line in self.filtered(lambda l: l.product_id):
            msg = _(f"Extra line with {line.product_id.display_name}")
            line.order_id.message_post(body=msg)

    def _hook_on_written_confirmed_lines(self, write_vals, previous_vals):
        # previous_qty_invoiced = previous_vals.get("previous_qty_invoiced")
        precision = self.env["decimal.precision"].precision_get("Product Unit")
        for line in self:
            if (
                "product_qty" in write_vals
                and float_compare(
                    previous_vals[line.id].get("product_qty"),
                    line.product_qty,
                    precision_digits=precision,
                )
                != 0
            ):
                line.order_id.message_post_with_source(
                    "purchase.track_po_line_template",
                    subtype_xmlid="mail.mt_note",
                    render_values={
                        "line": self,
                        "product_qty": line.product_qty,
                    },
                )
            if (
                "qty_transfered" in write_vals
                and float_compare(
                    previous_vals[line.id].get("qty_transfered"),
                    line.qty_transfered,
                    precision_digits=precision,
                )
                != 0
            ):
                # don't track anything when coming from the accrued expense entry wizard
                # as it is only computing fields at a past date to get relevant amounts
                # and doesn't actually change anything to the current record
                if not self.env.context.get("accrual_entry_date"):
                    line.order_id.message_post_with_source(
                        "purchase.track_po_line_qty_transfered_template",
                        subtype_xmlid="mail.mt_note",
                        render_values={
                            "line": self,
                            "qty_transfered": line.qty_transfered,
                        },
                    )

    def _merge_po_line(self, rfq_line):
        self.product_qty += rfq_line.product_qty
        self.price_unit = min(self.price_unit, rfq_line.price_unit)

    def _sanitize_create_display_type_vals(self, create_vals_list):
        """Sanitize the values to be used for creating a purchase order line with display_type."""
        for vals in create_vals_list:
            if vals.get("display_type") or self.default_get(["display_type"]).get(
                "display_type"
            ):
                vals.update(
                    product_id=False,
                    product_uom_id=False,
                    product_qty=False,
                    price_unit=False,
                    date_planned=False,
                )

    def _update_date_planned(self, updated_date):
        self.date_planned = updated_date

    def _validate_analytic_distribution(self):
        for line in self.filtered(lambda l: not l.display_type):
            line._validate_distribution(
                product=line.product_id.id,
                business_domain="purchase_order",
                company_id=line.company_id.id,
            )

    def _get_compute_name(self, seller, params=False):
        # record product names to avoid resetting custom descriptions
        default_names = []
        sellers = self.product_id._prepare_sellers(params=params)
        lang = get_lang(self.env, self.partner_id.lang).code
        product_ctx = {
            "partner_id": None,
            "seller_id": None,
            "lang": lang,
        }
        default_names.append(
            self._get_product_purchase_description(
                self.product_id.with_context(product_ctx)
            )
        )
        for seller in sellers:
            product_ctx = {
                "seller_id": seller.id,
                "lang": lang,
            }
            default_names.append(
                self._get_product_purchase_description(
                    self.product_id.with_context(product_ctx)
                )
            )
        if not self.name or self.name in default_names:
            product_ctx = {
                "seller_id": seller.id or None,
                "lang": lang,
            }
            self.name = self._get_product_purchase_description(
                self.product_id.with_context(product_ctx)
            )

    def _get_compute_product_qty(self):
        """Suggest a minimal quantity based on the seller"""
        date = (
            self.order_id.date_order
            and self.order_id.date_order.date()
            or fields.Date.context_today(self)
        )
        seller_min_qty = self.product_id.seller_ids.filtered(
            lambda r: r.partner_id == self.order_id.partner_id
            and (not r.product_id or r.product_id == self.product_id)
            and (not r.date_start or r.date_start <= date)
            and (not r.date_end or r.date_end >= date)
        ).sorted(key=lambda r: r.min_qty)
        if seller_min_qty:
            self.product_qty = seller_min_qty[0].min_qty or 1.0
            self.product_uom_id = seller_min_qty[0].product_uom_id
        else:
            self.product_qty = 1.0

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
        :return: desired Schedule Date for the PO line"""
        date_order = po.date_order if po else self.date_order
        if date_order:
            return date_order + relativedelta(days=seller.delay if seller else 0)
        else:
            return datetime.today() + relativedelta(days=seller.delay if seller else 0)

    def _get_invoice_line_ids(self):
        self.ensure_one()
        if self._context.get("accrual_entry_date"):
            return self.invoice_line_ids.filtered(
                lambda l: l.move_id.invoice_date
                and l.move_id.invoice_date <= self._context["accrual_entry_date"]
            )

        else:
            return self.invoice_line_ids

    def _get_price_unit_gross(self):
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

    def _get_product_purchase_description(self, product_lang):
        self.ensure_one()
        name = product_lang.display_name
        if product_lang.description_purchase:
            name += "\n" + product_lang.description_purchase
        return name

    def _get_select_sellers_params(self):
        self.ensure_one()
        return {
            "order_id": self.order_id,
        }

    def _prepare_aml_vals(self, **optional_values):
        """Prepare the values to create an invoice line from a purchase order line.
        :param move: an account.move object.
        :rtype: dict
        :return: A python dictionary with the keys neccesary to create an
        account.move.line object."""
        self.ensure_one()
        move = optional_values.get("move", False)
        aml_currency = move and move.currency_id or self.currency_id
        date = move and move.date or fields.Date.today()
        res = {
            "display_type": self.display_type or "product",
            "product_id": self.product_id.id,
            "product_uom_id": self.product_uom_id.id,
            "quantity": self.qty_to_invoice,
            "name": self.env["account.move.line"]._get_journal_items_full_name(
                self.name, self.product_id.display_name
            ),
            "price_unit": self.currency_id._convert(
                self.price_unit, aml_currency, self.company_id, date, round=False
            ),
            "discount": self.discount,
            "tax_ids": [Command.set(self.tax_ids.ids)],
            "purchase_line_ids": [Command.link(self.id)],
            "is_downpayment": self.is_downpayment,
        }
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
                "quantity": self.product_qty,
                "partner_id": self.order_id.partner_id,
                "currency_id": self.order_id.currency_id
                or self.order_id.company_id.currency_id,
                "rate": self.order_id.currency_rate,
                **kwargs,
            },
        )

    @api.model
    def _prepare_purchase_order_line(
        self, product_id, product_qty, product_uom, company_id, supplier, po
    ):
        partner = supplier.partner_id
        uom_po_qty = product_uom._compute_quantity(
            product_qty, product_id.uom_id, rounding_method="HALF-UP"
        )
        # _select_seller is used if the supplier have different price depending
        # the quantities ordered.
        today = fields.Date.today()
        seller = product_id.with_company(company_id)._select_seller(
            partner_id=partner,
            quantity=uom_po_qty,
            date=po.date_order and max(po.date_order.date(), today) or today,
            uom_id=product_id.uom_id,
        )
        if (
            seller
            and (seller.product_uom_id or seller.product_tmpl_id.uom_id) != product_uom
        ):
            uom_po_qty = product_id.uom_id._compute_quantity(
                uom_po_qty,
                seller.product_uom_id or seller.product_tmpl_id.uom_id,
                rounding_method="HALF-UP",
            )

        product_taxes = product_id.supplier_taxes_id.filtered(
            lambda x: x.company_id in company_id.parent_ids
        )
        taxes = po.fiscal_position_id.map_tax(product_taxes)
        if seller:
            price_unit = (
                (seller.product_uom_id or seller.product_tmpl_id.uom_id)._compute_price(
                    seller.price, product_uom
                )
                if product_uom
                else seller.price
            )
            price_unit = self.env["account.tax"]._fix_tax_included_price_company(
                price_unit, product_taxes, taxes, company_id
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
            lang=partner.lang,
            partner_id=partner.id,
        )
        name = product_lang.with_context(seller_id=seller.id).display_name
        if product_lang.description_purchase:
            name += "\n" + product_lang.description_purchase

        date_planned = self.order_id.date_planned or self._get_date_planned(
            seller, po=po
        )
        discount = seller.discount or 0.0
        return {
            "order_id": po.id,
            "product_id": product_id.id,
            "tax_ids": [(6, 0, taxes.ids)],
            "product_uom_id": product_uom.id or seller.product_uom_id.id,
            "product_qty": product_qty if product_uom else uom_po_qty,
            "price_unit": price_unit,
            "discount": discount,
            "date_planned": date_planned,
            "name": name,
        }

    def _prepare_write_previous_vals(self, write_vals):
        """Prepare the old values of the fields that are going to be written.
        This is used to check if the values have changed and to trigger the
        corresponding actions."""
        previous_vals = {}
        for line in self:
            previous_vals[line.id] = {}
            if "product_qty" in write_vals:
                previous_vals[line.id].update({"product_qty": line.product_qty})
            if "qty_transfered" in write_vals:
                previous_vals[line.id].update({"qty_transfered": line.qty_transfered})
            if "qty_invoiced" in write_vals:
                previous_vals[line.id].update({"qty_invoiced": line.qty_invoiced})
        return previous_vals

    # ------------------------------------------------------------
    # VALIDATIONS
    # ------------------------------------------------------------

    def _cant_be_unlinked(self):
        """Check whether given lines can be deleted or not.

        * Lines cannot be deleted if the order is confirmed.
        * Sections and Notes can always be deleted.

        :returns: Purchase Order Lines that cannot be deleted
        :rtype: `purchase.order.line` recordset"""
        return self.filtered(
            lambda line: line.state == "purchase" and not line.display_type
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
