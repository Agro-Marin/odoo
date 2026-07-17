from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

# Maximum number of products listed individually in chatter messages
# before switching to a count-only summary.
CHATTER_PRODUCT_LIST_THRESHOLD = 50


class OrderLineFieldsMixin(models.AbstractModel):
    """Common structural fields and validation for order lines.

    Provides:
    - Standard fields (``sequence``, ``display_type``, ``product_id``, etc.)
    - SQL constraints for accountable/non-accountable lines
    - Section/subsection hierarchy (``_compute_parent_id``)
    - Create/write/unlink validation framework (display type, locked orders)
    - Transfer quantity tracking (``qty_transferred`` & friends)

    Fields that **must** be defined by concrete models:

    - ``order_id``: Many2one to the parent order
    - ``company_id``/``currency_id``/``partner_id``/``state``/``locked``:
      related to the parent order
    - ``parent_id``: Many2one to self (with ``compute='_compute_parent_id'``)
    """

    _name = "order.line.fields.mixin"
    _description = "Common Order Line Fields"

    # ─── Structural Fields ─────────────────────────────────────────

    sequence = fields.Integer(string="Sequence", default=10)

    display_type = fields.Selection(
        selection=[
            ("line_section", "Section"),
            ("line_subsection", "Subsection"),
            ("line_note", "Note"),
        ],
        default=False,
    )

    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        change_default=True,
        check_company=True,
        domain=lambda self: self._domain_product_id(),
        ondelete="restrict",
        index="btree_not_null",
    )

    product_template_attribute_value_ids = fields.Many2many(
        related="product_id.product_template_attribute_value_ids",
        depends=["product_id"],
    )
    product_name_translated = fields.Text(
        compute="_compute_product_name_translated",
    )
    product_is_archived = fields.Boolean(
        compute="_compute_product_is_archived",
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
        domain='[("id", "in", allowed_uom_ids)]',
        ondelete="restrict",
    )

    name = fields.Text(
        string="Description",
        required=True,
        compute="_compute_name",
        store=True,
        precompute=True,
        readonly=False,
    )

    is_downpayment = fields.Boolean(
        string="Is a down payment",
    )

    is_expense = fields.Boolean(
        string="Is expense",
        help="Is true if the order line comes from an expense or a vendor bill",
    )

    # ─── SQL Constraints ───────────────────────────────────────────

    _accountable_required_fields = models.Constraint(
        """CHECK(
            display_type IS NOT NULL
            OR is_downpayment
            OR (
                product_id IS NOT NULL
                AND product_uom_id IS NOT NULL
            )
        )""",
        "Missing required fields on accountable order line.",
    )
    _non_accountable_null_fields = models.Constraint(
        """CHECK(
            display_type IS NULL
            OR (
                product_id IS NULL
                AND (price_unit IS NULL OR price_unit = 0)
                AND product_uom_id IS NULL
                AND (product_qty IS NULL OR product_qty = 0)
                AND (product_uom_qty IS NULL OR product_uom_qty = 0)
            )
        )""",
        "Forbidden values on non-accountable order line",
    )

    # ─── Routing ───────────────────────────────────────────────────

    def _get_order_type(self):
        """Return the order type identifier (``'sale'`` or ``'purchase'``)."""
        raise NotImplementedError(f"{self._name} must implement _get_order_type()")

    def _domain_product_id(self):
        """Domain for selectable products, routed by order type."""
        return [(f"{self._get_order_type()}_ok", "=", True)]

    # ─── CRUD ──────────────────────────────────────────────────────

    @api.model
    def _get_display_type_nullify_vals(self):
        """Values nulled out on display lines (sections/notes) at creation.

        Purchase extends with ``date_planned``.
        """
        return {
            "product_id": False,
            "price_unit": False,
            "product_qty": False,
            "product_uom_qty": False,
            "product_uom_id": False,
        }

    @api.model_create_multi
    def create(self, vals_list):
        """Nullify accountable values on display lines and run the
        confirmed-order creation hook."""
        nullify_vals = self._get_display_type_nullify_vals()
        for vals in vals_list:
            if vals.get("display_type") or self.default_get(["display_type"]).get(
                "display_type",
            ):
                vals.update(nullify_vals)

        lines = super().create(vals_list)

        # Hook for lines created on confirmed orders (messaging, pickings, ...)
        lines.filtered(
            lambda line: line.order_id.state == "done",
        )._hook_on_created_confirmed_lines()

        return lines

    def write(self, vals):
        """Validate writes and track quantity changes on confirmed orders.

        Dispatches to validation methods registered via
        ``_get_validate_write_vals_methods()``, captures done-line quantity
        changes before the write, then posts them after.
        """
        self._validate_write_vals(vals)
        tracked = [f for f in self._get_tracked_qty_fields() if f in vals]
        changes = self._collect_qty_changes(vals, tracked) if tracked else {}
        result = super().write(vals)
        for field_name, field_changes in changes.items():
            self._post_quantity_changes(field_name, field_changes)
        return result

    def _get_tracked_qty_fields(self):
        """Quantity fields whose changes are tracked on confirmed orders.

        Sale tracks ``product_qty``; purchase also tracks ``qty_transferred``.
        """
        return ["product_qty"]

    def _collect_qty_changes(self, vals, tracked_fields):
        """Capture done-line quantity changes before the write.

        :return: ``{field_name: [{"line", "old_qty", "new_qty"}, ...]}``
        """
        precision = self.env["decimal.precision"].precision_get("Product Unit")
        changes = defaultdict(list)
        for field_name in tracked_fields:
            for line in self:
                if (
                    line.order_id.state == "done"
                    and float_compare(
                        line[field_name],
                        vals[field_name],
                        precision_digits=precision,
                    )
                    != 0
                ):
                    changes[field_name].append(
                        {
                            "line": line,
                            "old_qty": line[field_name],
                            "new_qty": vals[field_name],
                        },
                    )
        return changes

    def _post_quantity_changes(self, field_name, changes):
        """Post tracking messages for done-line quantity changes.

        No-op by default.  Sale posts a Markup list; purchase renders mail
        templates grouped by order.
        """
        return

    # ─── Unit of Measure ───────────────────────────────────────────

    @api.depends("product_id", "product_id.uom_id", "product_id.uom_ids")
    def _compute_allowed_uom_ids(self):
        for line in self:
            line.allowed_uom_ids = (
                line.product_id.uom_id
                | line.product_id.uom_ids
                | line._get_extra_allowed_uoms()
            )

    def _get_extra_allowed_uoms(self):
        """Extra UoMs allowed on the line (purchase adds seller UoMs)."""
        return self.env["uom.uom"]

    @api.depends("product_id")
    def _compute_product_uom_id(self):
        """Set the UoM from the product default when product changes.

        Subclasses extend the trigger set and override the default (purchase
        prefers the seller UoM).
        """
        for line in self:
            if not line.product_uom_id or (
                line._origin.product_id and line._origin.product_id != line.product_id
            ):
                line.product_uom_id = line._get_default_product_uom()

    def _get_default_product_uom(self):
        """Default UoM for a new/changed line (purchase → seller UoM)."""
        return self.product_id.uom_id

    # ─── Description ───────────────────────────────────────────────

    @api.depends("product_id")
    def _compute_name(self):
        """Set the line description from the product in the right language.

        Subclasses extend the ``@api.depends`` trigger set (sale adds combo
        links + down payments, purchase adds partner/seller) and supply
        ``_get_default_line_description``.
        """
        for line in self:
            if not line._name_should_be_computed():
                continue
            lang = line._get_line_description_lang()
            if lang != self.env.lang:
                line = line.with_context(lang=lang)
            line.name = line._get_default_line_description()

    def _name_should_be_computed(self):
        """Whether ``name`` is auto-computed for this line.

        Base: product lines only.  Sale also computes for down payments.
        """
        return bool(self.product_id)

    def _get_line_description_lang(self):
        """Language used to render the line description.

        Sale uses the order language; purchase uses the partner language.
        """
        return self.env.lang

    def _get_default_line_description(self):
        """Return the default line description (product/seller specific)."""
        raise NotImplementedError(
            f"{self._name} must implement _get_default_line_description()"
        )

    @api.depends("product_id")
    def _compute_product_name_translated(self):
        """Product display name rendered in the line's description language."""
        for line in self:
            line.product_name_translated = line.product_id.with_context(
                lang=line._get_line_description_lang(),
            ).display_name

    @api.depends("product_id")
    def _compute_product_is_archived(self):
        for line in self:
            line.product_is_archived = line.product_id and not line.product_id.active

    # ─── Section/Subsection Hierarchy ──────────────────────────────

    def _compute_parent_id(self):
        """Compute the parent section/subsection for each line.

        Hierarchy: section → subsection → product lines.
        """
        target_lines = set(self)
        for order, lines in self.grouped("order_id").items():
            if not order:
                lines.parent_id = False
                continue
            last_section = False
            last_sub = False
            for line in order.line_ids.sorted("sequence"):
                if line.display_type == "line_section":
                    last_section = line
                    if line in target_lines:
                        line.parent_id = False
                    last_sub = False
                elif line.display_type == "line_subsection":
                    if line in target_lines:
                        line.parent_id = last_section
                    last_sub = line
                elif line in target_lines:
                    line.parent_id = last_sub or last_section

    def get_line_parent_section(self):
        """Return the section this line belongs to (skipping subsections)."""
        if not self.display_type and self.parent_id.display_type == "line_subsection":
            return self.parent_id.parent_id

        return self.parent_id

    # ─── Write Validation ──────────────────────────────────────────

    def _validate_write_vals(self, write_vals):
        """Run all registered write validators."""
        for method_name in self._get_validate_write_vals_methods():
            getattr(self, method_name)(write_vals)

    def _get_validate_write_vals_methods(self):
        """Return validator method names for write operations.

        Override in child models to add model-specific validators.
        Sale adds ``'_validate_write_product_and_uom'``.
        """
        return [
            "_validate_write_display_type",
            "_validate_write_locked_order",
        ]

    def _is_display_type_change_allowed(self, line, new_type):
        """Whether a display type transition is allowed on an existing line.

        Sale overrides to allow subsection → section promotion.
        """
        return False

    def _validate_write_display_type(self, write_vals):
        """Prevent changing ``display_type`` on existing lines."""
        if "display_type" not in write_vals:
            return

        new_type = write_vals.get("display_type")
        lines = self.filtered(
            lambda l: (
                l.display_type != new_type
                and not self._is_display_type_change_allowed(l, new_type)
            ),
        )
        if not lines:
            return

        if len(lines) == 1:
            raise UserError(
                _(
                    "You cannot change the type of %(line_type)s '%(line_id)s'. "
                    "Instead, delete the current line and create a new line of the proper type.",
                    line_type=self._description.lower(),
                    line_id=self._get_line_identifier(lines[0]),
                ),
            )
        line_ids = [self._get_line_identifier(l) for l in lines[:5]]
        error_msg = ", ".join(line_ids)
        if len(lines) > 5:
            error_msg += _(" and %s more", len(lines) - 5)
        raise UserError(
            _(
                "You cannot change the type of %(count)s %(line_type)s lines (%(lines)s). "
                "Instead, delete these lines and create new lines of the proper type.",
                count=len(lines),
                line_type=self._description.lower(),
                lines=error_msg,
            ),
        )

    def _validate_write_locked_order(self, write_vals):
        """Prevent modification of protected fields on locked orders."""
        locked_lines = self.filtered(lambda l: l.locked)
        if not locked_lines:
            return

        protected_fields = self._get_protected_fields()
        protected_fields_modified = list(set(protected_fields) & set(write_vals.keys()))
        if not protected_fields_modified:
            return

        # Allow changing name for downpayment lines
        if "name" in protected_fields_modified and all(
            locked_lines.mapped("is_downpayment"),
        ):
            protected_fields_modified.remove("name")

        if not protected_fields_modified:
            return

        fields_info = (
            self.env["ir.model.fields"]
            .sudo()
            .search(
                [
                    ("name", "in", protected_fields_modified),
                    ("model", "=", self._name),
                ],
            )
        )
        if fields_info:
            raise UserError(
                _(
                    "It is forbidden to modify the following fields in a locked order:\n%s",
                    "\n".join(fields_info.mapped("field_description")),
                ),
            )

    def _get_protected_fields(self):
        """Fields that should not be modified on a locked order."""
        return [
            "product_id",
            "name",
            "price_unit",
            "product_uom_id",
            "product_qty",
            "tax_ids",
            "analytic_distribution",
            "discount",
        ]

    def _get_line_identifier(self, line):
        """Return a human-readable identifier for error messages."""
        if line.product_id:
            return line.product_id.display_name
        elif line.name:
            # Truncate long descriptions to the first line only
            name = line.name.split("\n")[0]
            return name[:50] + "..." if len(name) > 50 else name
        else:
            return _("Line #%s", line.sequence or line.id)

    # ─── Unlink Validation ─────────────────────────────────────────

    @api.ondelete(at_uninstall=False)
    def _unlink_except_confirmed(self):
        """Prevent deletion of confirmed order lines."""
        lines_to_block = self._check_line_unlink()
        if lines_to_block:
            state_description = dict(
                self._fields["state"]._description_selection(self.env),
            )
            state_label = state_description.get(
                lines_to_block[0].state,
                lines_to_block[0].state,
            )
            raise UserError(
                _(
                    "Cannot delete a %(line_type)s which is in state '%(state)s'.\n"
                    "Once an order is confirmed, you can't remove lines that have "
                    "been invoiced or transferred (we need to track if something "
                    "gets invoiced or transferred).\nSet the quantity to 0 instead.",
                    line_type=self._description.lower(),
                    state=state_label,
                ),
            )

    def _check_line_unlink(self):
        """Return lines that cannot be deleted.

        Confirmed (``done``) lines without ``display_type`` cannot be deleted.

        :rtype: recordset
        """
        return self.filtered(
            lambda line: line.state == "done" and not line.display_type,
        )

    # ─── Transfer Tracking ─────────────────────────────────────────

    qty_transferred_method = fields.Selection(
        selection=[
            ("manual", "Manual"),
            ("analytic", "Analytic From Expenses"),
            ("stock_move", "Stock Moves"),
        ],
        string="Transferred Qty Method",
        compute="_compute_qty_transferred_method",
        store=True,
        precompute=True,
        help="Method used to compute the transferred quantity:\n"
        "  - Manual: set manually on the line\n"
        "  - Analytic: sum of analytic line unit amounts\n"
        "  - Stock Moves: from confirmed pickings\n",
    )
    qty_transferred = fields.Float(
        string="Transferred Qty",
        digits="Product Unit",
        compute="_compute_qty_transferred",
        store=True,
        readonly=False,
        copy=False,
    )
    qty_to_transfer = fields.Float(
        digits="Product Unit",
        copy=False,
    )
    # Same as `qty_transferred` but non-stored and depending on the context.
    qty_transferred_at_date = fields.Float(
        string="Transferred",
        digits="Product Unit",
        compute="_compute_qty_transferred_at_date",
    )

    @api.depends("is_expense", "product_id")
    def _compute_qty_transferred_method(self):
        """Determine the transfer computation method based on product type.

        Expense lines always use analytic.  Services default to manual.
        Consumables default to stock_move (overridden by stock modules).
        """
        for line in self:
            if line.is_expense:
                line.qty_transferred_method = "analytic"
            elif line.product_id and line.product_type == "service":
                line.qty_transferred_method = "manual"
            elif line.product_id and line.product_type == "consu":
                line.qty_transferred_method = "stock_move"
            else:
                line.qty_transferred_method = False

    @api.depends("qty_transferred_method")
    def _compute_qty_transferred(self):
        """Reset manual lines to zero.  Child models extend per method.

        Overrides should take their concerned lines, compute and set
        ``qty_transferred``, and call ``super()`` with the remaining records.
        """
        lines_manual = self.filtered(
            lambda line: line.qty_transferred_method == "manual",
        )
        lines_manual.qty_transferred = 0.0

    @api.depends_context("accrual_entry_date")
    @api.depends("qty_transferred")
    def _compute_qty_transferred_at_date(self):
        if not self._date_in_the_past():
            # Avoid a useless compute if we don't look in the past.
            for line in self:
                line.qty_transferred_at_date = line.qty_transferred
            return
        transferred_quantities = self._prepare_qty_transferred()
        for line in self:
            line.qty_transferred_at_date = transferred_quantities[line]

    def _prepare_qty_transferred(self):
        """Return the transferred quantity per line for at-date computations.

        Base: manual lines keep their value, others get 0.  Sale overrides
        with the analytic-based computation.

        :rtype: dict
        """
        transferred_qties = defaultdict(float)
        for line in self:
            if line.qty_transferred_method == "manual":
                transferred_qties[line] = line.qty_transferred or 0.0
            else:
                transferred_qties[line] = 0.0
        return transferred_qties

    def _invoiced_on_transferred(self):
        """Whether this line's invoiced/billed quantity is its transferred
        (delivered/received) quantity rather than its ordered quantity.

        Base lines are never invoiced on transferred qty; sale/purchase
        override to read their respective policy field.
        """
        return False

    def _assert_transferred_uom_convertible(self):
        """Posting-boundary guard for the leniently-computed transferred qty.

        ``_compute_qty_transferred`` converts move/BoM quantities into the line
        UoM through ``_compute_quantity_reconcile``, which *degrades* (returns
        the quantity unconverted) instead of raising when the units share no
        common reference — so opening or editing an order carrying legacy
        incompatible-UoM data never blocks. That leniency must not reach a
        financial posting: before the transferred quantity sizes an
        invoice/bill line (``qty_to_invoice``) or an accrual amount, re-run the
        very same computation under the ``uom_reconcile_strict`` context so an
        impossible conversion raises here — at the deliberate posting action —
        instead of silently posting an unconverted quantity.

        Reusing ``_compute_qty_transferred`` verbatim (rather than duplicating
        the per-method move/BoM selection) validates stock-move, kit and
        analytic lines exactly as they are computed.
        """
        for line in self.filtered(lambda l: l._invoiced_on_transferred()):
            try:
                line.with_context(
                    uom_reconcile_strict=True
                )._compute_qty_transferred()
            except UserError as error:
                raise UserError(
                    _(
                        "Cannot invoice “%(line)s”: its transferred "
                        "(delivered/received) quantity relies on a unit of "
                        "measure conversion that is not possible, so the line "
                        "cannot be sized for invoicing. Align the units of "
                        "measure on the order line and its transfers, then try "
                        "again.\n\n%(detail)s",
                        line=line.display_name,
                        detail=error.args[0] if error.args else "",
                    )
                ) from error

    @api.model
    def _date_in_the_past(self):
        """Whether the context accrual date is before today."""
        if "accrual_entry_date" not in self.env.context:
            return False
        accrual_date = fields.Date.from_string(self.env.context["accrual_entry_date"])
        return accrual_date < fields.Date.today()

    # ─── Analytic Validation ───────────────────────────────────────

    def _lines_to_validate_analytic_distribution(self):
        """Lines whose analytic distribution must be validated.

        Sale overrides to only validate draft lines.
        """
        return self.filtered(lambda line: not line.display_type)

    def _validate_analytic_distribution(self):
        """Validate the analytic distribution of the relevant lines."""
        business_domain = f"{self._get_order_type()}_order"
        for line in self._lines_to_validate_analytic_distribution():
            line._validate_distribution(
                product=line.product_id.id,
                business_domain=business_domain,
                company_id=line.company_id.id,
            )

    # ─── Lifecycle Hooks ────────────────────────────────────────────

    def _hook_on_created_confirmed_lines(self):
        """Post chatter messages when lines are added to confirmed orders.

        Groups lines by order and posts a single message per order.
        Uses ``CHATTER_PRODUCT_LIST_THRESHOLD`` to decide between
        an itemized list or a count-only summary.
        """
        if self.env.context.get("no_log_for_new_lines"):
            return

        lines_by_order = defaultdict(self.browse)
        for line in self:
            if line.product_id:
                lines_by_order[line.order_id] += line

        for order, order_lines in lines_by_order.items():
            count = len(order_lines)
            if count == 1:
                msg = _("Extra line with %s", order_lines.product_id.display_name)
            elif count <= CHATTER_PRODUCT_LIST_THRESHOLD:
                product_list = (
                    "<ul>"
                    + "".join(
                        f"<li>{p}</li>"
                        for p in order_lines.mapped("product_id.display_name")
                    )
                    + "</ul>"
                )
                msg = _(
                    "Added %(count)s extra lines: %(products)s",
                    count=count,
                    products=product_list,
                )
            else:
                msg = _(
                    "Added %(count)s extra lines to this %(order_type)s",
                    count=count,
                    order_type=order._description.lower(),
                )
            order.message_post(body=msg)

    # ─── Catalog ────────────────────────────────────────────────────

    def _get_product_catalog_lines_data(self, **kwargs):
        """Return the product-catalog payload for the lines in ``self``.

        Shared three-branch skeleton (single line / several lines sharing one
        product / empty recordset).  The payload construction diverges — sale
        prices from the pricelist, purchase from seller data — and is
        delegated to hooks.  ``order.mixin._default_order_line_values`` calls
        this on an empty recordset, which only hits the generic last branch.

        :raise ValueError: if the lines in ``self`` have different products.
        :rtype: dict
        :return: at least ``{'quantity': float}``; non-empty recordsets add
            ``price``, ``readOnly`` and model-specific keys via the hooks.
        """
        if len(self) == 1:
            return self._get_catalog_single_line_data(**kwargs)
        elif self:
            self.product_id.ensure_one()
            data = self[0]._get_catalog_multi_line_data(**kwargs)
            data["quantity"] = sum(
                self.mapped(
                    lambda line: line.product_uom_id._compute_quantity_report(
                        qty=line.product_qty,
                        to_unit=line.product_id.uom_id,
                    ),
                ),
            )
            data["readOnly"] = True
            return data
        return {"quantity": 0}

    def _get_catalog_single_line_data(self, **kwargs):
        """Catalog payload for a single line (quantity, price, readOnly, …)."""
        raise NotImplementedError(
            f"{self._name} must implement _get_catalog_single_line_data()"
        )

    def _get_catalog_multi_line_data(self, **kwargs):
        """Base catalog payload when several lines share one product.

        Called on the first line; returns the price payload — the generic
        skeleton adds the aggregated ``quantity`` and ``readOnly``.
        """
        raise NotImplementedError(
            f"{self._name} must implement _get_catalog_multi_line_data()"
        )

    # ─── Actions ────────────────────────────────────────────────────

    @api.readonly
    def action_add_from_catalog(self):
        """Redirect the catalog action from the line to the parent order."""
        order_model = self._fields["order_id"].comodel_name
        order = self.env[order_model].browse(self.env.context.get("order_id"))
        return order.with_context(child_field="line_ids").action_add_from_catalog()

    def action_view_order(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": self._fields["order_id"].comodel_name,
            "res_id": self.order_id.id,
            "view_mode": "form",
        }
