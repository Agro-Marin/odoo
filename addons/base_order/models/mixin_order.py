from collections import defaultdict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.models import MAGIC_COLUMNS
from odoo.tools import SQL, OrderedSet, format_list


class MixinOrder(models.AbstractModel):
    """Base mixin for sale.order and purchase.order.

    Consolidates patterns that were duplicated across both modules.
    Child models implement ``_get_order_type()`` and override hooks
    for model-specific behaviour.

    Usage::

        class SaleOrder(models.Model):
            _name = "sale.order"
            _inherit = ["mixin.order", "mixin.order.amount", ...]

            def _get_order_type(self):
                return "sale"
    """

    _name = "mixin.order"
    _description = "Order Management Base"
    _inherit = [
        "mixin.mail.thread",
        "mixin.mail.activity",
        "mixin.portal",
        "mixin.product.catalog",
    ]

    # Legal ``state`` transitions on raw writes. Subclasses override to add
    # their own states (e.g. ``sent``).
    _STATE_TRANSITIONS = {
        "draft": {"done", "cancel"},
        "done": {"cancel"},
        "cancel": {"draft"},
    }
    # Fields still writable while an order is locked. ``access_token`` is a
    # mixin.portal technical field generated on demand (``_portal_ensure_token``)
    # when sharing/notifying — it is not a business field and must remain
    # writable even on locked orders, matching upstream (which has no hard
    # locked-write guard).
    # Communication/acknowledgement tracking fields are lifecycle metadata,
    # not business content: actions like ``action_acknowledge`` / marking an
    # order as sent/printed legitimately fire on confirmed (hence often locked)
    # orders, matching upstream which has no hard locked-write guard.
    _LOCKED_WRITABLE_FIELDS = {
        "locked",
        "priority",
        "access_token",
        "acknowledged",
        "sent",
        "count_sent",
        "printed_before",
        "count_print",
    }

    @property
    def _rec_names_search(self):
        base_fields = self._get_fields_rec_search_base()
        if self.env.context.get(self._get_display_name_context_key()):
            return [*base_fields, "partner_id.name"]
        return base_fields

    def _get_fields_rec_search_base(self):
        """Base fields searched by name. Purchase adds ``partner_ref``."""
        return ["name"]

    def _get_display_name_context_key(self):
        """Context key that toggles the partner name in the display name.

        Defaults to ``'<order_type>_show_partner_name'`` — matches both
        ``sale_show_partner_name`` and ``purchase_show_partner_name``.
        """
        return f"{self._get_order_type()}_show_partner_name"

    # ------------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------------

    # Declared here for the same reason as ``date_commitment``: this mixin
    # already consumes ``line_ids`` throughout — the company constraint, the
    # archived-product and catalog computes, confirmation validation, copy_data.
    # Concrete models re-declare it with their own ``comodel_name`` only; the
    # placeholder comodel is the abstract line mixin, which declares the
    # matching ``order_id`` inverse.
    line_ids = fields.One2many(
        comodel_name="mixin.order.line.fields",
        inverse_name="order_id",
        string="Order Lines",
        copy=True,
    )
    product_id = fields.Many2one(
        related="line_ids.product_id",
        comodel_name="product.product",
        string="Product",
    )

    name = fields.Char(
        string="Order Reference",
        required=True,
        default=lambda self: _("New"),
        # Editable to match upstream sale/purchase: users may set a custom
        # reference, and base_import excludes readonly fields, which would drop
        # the "Order Reference" column from the RFQ/quotation import templates.
        readonly=False,
        copy=False,
        index="trigram",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("done", "Confirmed"),
            ("cancel", "Cancelled"),
        ],
        string="Status",
        default="draft",
        readonly=True,
        copy=False,
        index=True,
        tracking=True,
    )
    priority = fields.Selection(
        selection=[
            ("0", "Normal"),
            ("1", "Urgent"),
        ],
        string="Priority",
        default="0",
        index=True,
    )

    # Dates
    date_order = fields.Datetime(
        string="Order Date",
        required=True,
        default=fields.Datetime.now,
        copy=False,
        index=True,
        help="Creation date of draft/sent orders,\nConfirmation date of confirmed orders.",
    )
    date_confirmed = fields.Datetime(
        string="Confirmation Date",
        readonly=True,
        copy=False,
        index=True,
        help="Date when the order was confirmed.",
    )
    # Declared here because this mixin already *consumes* it: the ``is_late``
    # domain (``_get_domain_is_late``) searches ``date_commitment``, so every
    # consumer has to supply it. Concrete models layer their own attributes on
    # top — sale leaves it manual, purchase computes it from its lines — but
    # the field, and the meaning, are the mixin's. See Appendix A of
    # doc/coding_guidelines.rst for the purchase ``date_planned`` rename that
    # gave the concept one name across order types.
    date_commitment = fields.Datetime(
        string="Commitment Date",
        copy=False,
        help="The date somebody committed to: the delivery date promised to "
        "the customer on a sale, the arrival date promised by the vendor on a "
        "purchase.",
    )
    date_validity = fields.Date(
        string="Expiration",
        compute="_compute_date_validity",
        store=True,
        precompute=True,
        readonly=False,
        copy=False,
        help="Validity of the quotation, after which it expires.",
    )

    # Company & financial
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    company_price_include = fields.Selection(
        related="company_id.account_price_include",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        required=True,
        compute="_compute_currency_id",
        store=True,
        precompute=True,
        readonly=False,
        ondelete="restrict",
    )
    currency_rate = fields.Float(
        string="Currency Rate",
        digits=0,
        compute="_compute_currency_rate",
        store=True,
        precompute=True,
    )

    # Partner
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Partner",
        required=True,
        change_default=True,
        check_company=True,
        index=True,
        tracking=True,
    )
    commercial_partner_id = fields.Many2one(
        related="partner_id.commercial_partner_id",
        store=True,
        index=True,
    )

    # Responsible user
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Responsible",
        compute="_compute_user_id",
        store=True,
        precompute=True,
        readonly=False,
        index=True,
        tracking=True,
        domain="[('share', '=', False), ('company_ids', '=', company_id)]",
    )

    # Payment & fiscal
    payment_term_id = fields.Many2one(
        comodel_name="account.payment.term",
        string="Payment Terms",
        compute="_compute_payment_term_id",
        store=True,
        precompute=True,
        readonly=False,
        check_company=True,
        domain="[('company_id', 'in', [False, company_id])]",
    )
    fiscal_position_id = fields.Many2one(
        comodel_name="account.fiscal.position",
        string="Fiscal Position",
        compute="_compute_fiscal_position_id",
        store=True,
        precompute=True,
        readonly=False,
        check_company=True,
        domain="[('company_id', 'in', [False, company_id])]",
        help="Fiscal positions are used to adapt taxes and accounts for particular "
        "partners or orders/invoices. The default value comes from the partner.",
    )
    journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Journal",
        compute="_compute_journal_id",
        store=True,
        precompute=True,
        readonly=False,
        check_company=True,
        help="If set, the order will invoice in this journal; otherwise the "
        "journal with the lowest sequence is used.",
    )

    # Control fields
    locked = fields.Boolean(
        default=False,
        copy=False,
        tracking=True,
        help="Locked orders cannot be modified.",
    )
    acknowledged = fields.Boolean(
        string="Acknowledged",
        copy=False,
        tracking=True,
        help="It indicates that the partner has acknowledged the receipt of the order.",
    )

    # Communication tracking
    sent = fields.Boolean(
        default=False,
        copy=False,
        tracking=True,
        help="The order has been sent to the partner.",
    )
    count_sent = fields.Integer(
        string="Sent Count",
        default=0,
        copy=False,
    )
    printed_before = fields.Boolean(
        default=False,
        copy=False,
        tracking=True,
        help="The order has already been printed.",
    )
    count_print = fields.Integer(
        string="Print Count",
        default=0,
        copy=False,
    )

    # References
    origin = fields.Char(
        string="Source Document",
        copy=False,
        help="Reference of the document that generated this order request.",
    )
    partner_ref = fields.Char(
        string="Partner Reference",
        copy=False,
    )

    # Terms
    notes = fields.Html(string="Terms and Conditions")

    # Self-referential, so the placeholder points at this abstract model and
    # each concrete model re-declares it with its own comodel.
    duplicated_order_ids = fields.Many2many(
        comodel_name="mixin.order",
        compute="_compute_duplicated_order_ids",
    )

    # Computed status helpers
    is_expired = fields.Boolean(
        string="Is Expired",
        compute="_compute_is_expired",
    )
    is_late = fields.Boolean(
        string="Is Late",
        store=False,
        search="_search_is_late",
        help="True when the order is confirmed and its planned date has passed.",
    )
    type_name = fields.Char(
        string="Type Name",
        compute="_compute_type_name",
    )
    has_archived_products = fields.Boolean(
        compute="_compute_has_archived_products",
    )

    # ------------------------------------------------------------------
    # ORDER TYPE — primary routing key
    # ------------------------------------------------------------------

    def _get_order_type(self):
        """Return the order type identifier used as a routing key.

        :return: ``'sale'`` or ``'purchase'``
        :rtype: str
        """
        raise NotImplementedError(f"{self._name} must implement _get_order_type()")

    def _get_line_model(self):
        """Return the model name of the order line model."""
        return f"{self._name}.line"

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """Generate the sequence number using the order type as routing key."""
        seq_code = f"{self._get_order_type()}.order"
        for vals in vals_list:
            company_id = vals.get(
                "company_id",
                self.default_get(["company_id"])["company_id"],
            )
            # Ensures defaults are taken from the right company.
            self_comp = self.with_company(company_id)
            if vals.get("name", _("New")) == _("New"):
                date_order = vals.get(
                    "date_order",
                    self_comp.default_get(["date_order"])["date_order"],
                )
                seq_date = fields.Datetime.context_timestamp(
                    self_comp,
                    fields.Datetime.to_datetime(date_order),
                )
                vals["name"] = self_comp.env["ir.sequence"].next_by_code(
                    seq_code,
                    sequence_date=seq_date,
                )
        return super().create(vals_list)

    def write(self, vals):
        self._check_write_guards(vals)
        return super().write(vals)

    def copy_data(self, default=None):
        """Duplicate an order, copying only its copiable lines.

        When the caller doesn't pass ``line_ids`` explicitly, rebuild them from
        ``_get_order_lines_copiable()`` so that non-copiable lines (e.g. down
        payments) are dropped from the copy.  Identical in sale and purchase.
        """
        default = dict(default or {})
        default_has_no_order_line = "line_ids" not in default
        default.setdefault("line_ids", [])
        vals_list = super().copy_data(default=default)
        if default_has_no_order_line:
            for order, vals in zip(self, vals_list, strict=False):
                vals["line_ids"] = [
                    Command.create(line_vals)
                    for line_vals in order._get_order_lines_copiable().copy_data()
                ]
        return vals_list

    def _get_order_lines_copiable(self):
        """Return the order lines to duplicate when copying the order.

        Excludes down-payment lines (they belong to the original order's
        invoicing, not a fresh copy).  Override to refine the selection.
        """
        return self.line_ids.filtered(lambda line: not line.is_downpayment)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft_or_cancel(self):
        """Prevent deletion of confirmed orders."""
        confirmed = self.filtered(lambda o: o.state not in ("draft", "cancel"))
        if confirmed:
            raise UserError(
                _(
                    "Cannot delete confirmed %(desc)s. Cancel them first:\n%(orders)s",
                    desc=self._description,
                    orders=", ".join(confirmed.mapped("name")),
                ),
            )

    # ------------------------------------------------------------------
    # CONSTRAINTS
    # ------------------------------------------------------------------

    @api.constrains("company_id", "line_ids")
    def _check_line_ids_company_id(self):
        """Ensure all product lines belong to the same company as the order."""
        for order in self:
            invalid_companies = order.line_ids.product_id.company_id.filtered(
                lambda c, order=order: order.company_id not in c._accessible_branches(),
            )
            if invalid_companies:
                bad_products = order.line_ids.product_id.filtered(
                    lambda p, invalid=invalid_companies: (
                        p.company_id and p.company_id in invalid
                    ),
                )
                raise ValidationError(
                    _(
                        "Your %(desc)s contains products from company %(product_company)s "
                        "whereas your %(desc)s belongs to company %(quote_company)s.\n\n"
                        "Please change the company of your %(desc)s or remove the products "
                        "from other companies (%(bad_products)s).",
                        desc=self._description.lower(),
                        product_company=", ".join(
                            invalid_companies.sudo().mapped("display_name"),
                        ),
                        quote_company=order.company_id.display_name,
                        bad_products=", ".join(bad_products.mapped("display_name")),
                    ),
                )

    # ------------------------------------------------------------------
    # COMPUTE — identical in sale and purchase
    # ------------------------------------------------------------------

    @api.depends("company_id", "currency_id", "date_order")
    def _compute_currency_rate(self):
        for order in self:
            order.currency_rate = self.env["res.currency"]._get_conversion_rate(
                from_currency=order.company_id.currency_id,
                to_currency=order.currency_id,
                company=order.company_id,
                date=(order.date_order or fields.Datetime.now()).date(),
            )

    @api.depends("line_ids.product_id")
    def _compute_has_archived_products(self):
        """Flag orders whose lines reference an archived (inactive) product."""
        for order in self:
            order.has_archived_products = any(
                not product.active for product in order.line_ids.product_id
            )

    def _compute_display_name(self):
        for order in self:
            order.display_name = f"{order.name}{order._get_display_name_suffix()}"

    def _get_display_name_suffix(self):
        """Suffix appended to the order name in the display name.

        Empty by default; sale appends the partner name (under a context key),
        purchase appends ``partner_ref`` and an optional total.
        """
        return ""

    @api.depends("state", "date_validity")
    def _compute_is_expired(self):
        today = fields.Date.today()
        for order in self:
            order.is_expired = (
                order.state == "draft"
                and order.date_validity
                and order.date_validity < today
            )

    @api.depends("company_id")
    def _compute_date_validity(self):
        """Default expiration date from the company validity setting."""
        today = fields.Date.context_today(self)
        for order in self:
            days = order._get_validity_days()
            if days > 0:
                order.date_validity = today + timedelta(days=days)
            else:
                order.date_validity = False

    def _compute_journal_id(self):
        """Default to no journal (invoice creation then falls back to the
        lowest-sequence journal of the right type).  Available as an override
        point for models that want to force a specific journal."""
        self.journal_id = False

    @api.depends_context("lang")
    @api.depends("state")
    def _compute_type_name(self):
        for order in self:
            if order.state in ("draft", "cancel"):
                order.type_name = order._get_draft_type_name()
            else:
                order.type_name = order._get_confirmed_type_name()

    @api.depends("state", "partner_id", "origin")
    def _compute_duplicated_order_ids(self):
        """Compute potential duplicated orders based on key fields.

        Concrete models re-declare ``duplicated_order_ids`` with their own
        ``comodel_name`` and extend the dependencies with their reference
        field. (The dependencies are *unioned* across the MRO, so an override's
        ``@api.depends`` adds to this one rather than replacing it.)
        """
        draft_orders = self.filtered(lambda order: order.state == "draft")
        order_to_duplicate_orders = draft_orders._get_duplicate_orders()
        for order in draft_orders:
            duplicate_ids = order_to_duplicate_orders.get(order.id, [])
            order.duplicated_order_ids = [Command.set(duplicate_ids)]
        (self - draft_orders).duplicated_order_ids = False

    # ------------------------------------------------------------------
    # COMPUTE — shared skeleton, child overrides for specifics
    # ------------------------------------------------------------------

    @api.depends("company_id", "partner_id")
    def _compute_currency_id(self):
        """Default: company currency.

        Override in child models:
        - Sale: pricelist currency
        - Purchase: partner purchase currency property
        """
        for order in self:
            order.currency_id = order.company_id.currency_id

    @api.depends("partner_id")
    def _compute_user_id(self):
        """Assign the responsible user on partner change.

        The guard logic is shared.  Override ``_get_default_user_from_partner``
        to return the right user (salesperson vs buyer).
        """
        for order in self:
            if order.partner_id and not (order._origin.id and order.user_id):
                order.user_id = order._get_default_user_from_partner()

    @api.depends("company_id", "partner_id")
    def _compute_payment_term_id(self):
        """Default payment terms from the partner property (routed by type)."""
        field_name = self._get_partner_payment_term_field()
        for order in self:
            order = order.with_company(order.company_id)
            order.payment_term_id = order.partner_id[field_name]

    @api.depends("company_id", "partner_id")
    def _compute_fiscal_position_id(self):
        """Base implementation (purchase pattern — no shipping partner).

        Sale overrides to add ``partner_shipping_id`` to the cache key
        and pass it to ``_get_fiscal_position()``.
        """
        cache = {}
        for order in self:
            if not order.partner_id:
                order.fiscal_position_id = False
                continue

            key = (order.company_id.id, order.partner_id.id)
            if key not in cache:
                cache[key] = (
                    self.env["account.fiscal.position"]
                    .with_company(order.company_id)
                    ._get_fiscal_position(order.partner_id)
                    .id
                )
            order.fiscal_position_id = cache[key]

    # ------------------------------------------------------------------
    # SEARCH — is_late (search-only field, evaluated in SQL)
    # ------------------------------------------------------------------

    def _search_is_late(self, operator, value):
        if operator not in ("=", "!="):
            raise ValidationError(_("Unsupported operator."))
        domain = self._get_domain_is_late(operator, value)
        positive = (operator == "=" and value) or (operator == "!=" and not value)
        return self._get_is_late_search_domain(domain, positive)

    def _get_domain_is_late(self, operator, value):
        """Domain matching confirmed orders whose promised date has passed.

        Built on ``date_commitment``, the date a human committed to — sale's is
        the delivery date promised to the customer, purchase's the arrival date
        promised by the vendor. Both are stored, so both are searchable.

        This used to read ``date_planned``, which named that commitment on
        purchase but a *derived, unstored* estimate on sale. Searching it there
        raised "Cannot convert sale.order.date_planned to SQL because it is not
        stored", so ``is_late`` — declared on this mixin and therefore
        advertised on both models — could not be searched on a sale order at
        all.

        The explicit ``!= False`` term keeps orders with no promised date out of
        both the domain and its negation: nothing was promised, so nothing is
        late.
        """
        return Domain(
            [
                ("state", "=", "done"),
                ("date_commitment", "!=", False),
                ("date_commitment", "<=", fields.Datetime.now()),
            ]
        )

    def _get_is_late_search_domain(self, domain, positive):
        """Final search domain for ``is_late``.

        Base (sale's behaviour): the order-level domain or its negation.
        Purchase overrides to additionally require lines whose transferred
        quantity is below the ordered quantity.
        """
        return domain if positive else ~domain

    # ------------------------------------------------------------------
    # HOOKS — override in child models
    # ------------------------------------------------------------------

    def _get_draft_type_name(self):
        """Display name for draft/cancel state (e.g. 'Quotation')."""
        return _("Quotation")

    def _get_confirmed_type_name(self):
        """Display name for confirmed state (e.g. 'Sale Order', 'Purchase Order')."""
        order_type = self._get_order_type()
        return _("%(type)s Order", type=order_type.title())

    def _get_validity_days(self):
        """Return the number of validity days for new orders (0 = no expiry).

        :rtype: int
        """
        self.ensure_one()
        return 0

    def _get_partner_payment_term_field(self):
        """Return the partner property field holding default payment terms."""
        if self._get_order_type() == "sale":
            return "property_payment_term_id"
        return "property_supplier_payment_term_id"

    def _get_default_user_from_partner(self):
        """Return the user to assign as responsible.

        Override in child models to read from partner properties::

            Sale: partner.user_id or commercial_partner.user_id or env.user
            Purchase: partner.user_purchase_id or ... or env.user
        """
        self.ensure_one()
        return (
            self.env.user
            if self.env.user.has_group("base.group_user")
            else self.env["res.users"]
        )

    def _prepare_confirmation_values(self):
        """Values to write when confirming.

        Override to add model-specific date fields::

            Sale: {"state": "done", "date_order": now()}
            Purchase: {"state": "done", "date_confirmed": now()}
        """
        return {"state": "done"}

    def _get_confirmation_context(self):
        """Context used to run the post-confirmation hook.

        Sale overrides to drop ``default_name`` / ``default_user_id``.
        """
        return self.env.context

    def _action_confirm(self):
        """Post-confirmation hook.  Override for model-specific logic.

        Sale leaves empty; purchase creates supplier records.
        """

    def _action_cancel(self):
        """Perform cancellation: cancel draft invoices and write the state.

        ``invoice_ids`` comes from ``mixin.order.invoice``, which every concrete
        order (sale/purchase) composes, so it is always present here.
        """
        draft_invoices = self.invoice_ids.filtered(
            lambda invoice: invoice.state == "draft",
        )
        if draft_invoices:
            draft_invoices.action_cancel()
        self.write({"state": "cancel"})
        return True

    def _get_lock_setting_field(self):
        """Return the ``res.company`` field controlling auto-lock on confirm."""
        if self._get_order_type() == "sale":
            return "order_lock_so"
        return "order_lock_po"

    def _get_lock_setting_user(self):
        """Return the user whose auto-lock group membership is checked.

        Sale overrides to check the order creator instead of the current user.
        """
        self.ensure_one()
        return self.env.user

    def _should_be_locked(self):
        """Check if the order should auto-lock after confirmation."""
        self.ensure_one()
        order_type = self._get_order_type()
        company_locks = self.company_id[self._get_lock_setting_field()]
        return company_locks == "lock" or self._get_lock_setting_user().has_group(
            f"{order_type}.group_auto_done_setting",
        )

    def _is_readonly(self):
        """Whether the order should be treated as read-only in the UI.

        Sale overrides to add ``or self.locked``.
        """
        self.ensure_one()
        return self.state == "cancel"

    # ------------------------------------------------------------------
    # VALIDATION REGISTRY — _can_confirm / _can_cancel
    # ------------------------------------------------------------------

    def _can_confirm(self):
        """Run all confirmation validations.

        Extensible in two ways: override this method and call ``super()``,
        or (recommended) extend ``_get_can_confirm_validation_methods()``.

        :raises UserError: if any validation fails
        """
        for method_name in self._get_can_confirm_validation_methods():
            getattr(self, method_name)()

    def _get_can_confirm_validation_methods(self):
        """Return validator method names called by ``_can_confirm``.

        Extend via ``super()`` in child models or bridge modules::

            methods = super()._get_can_confirm_validation_methods()
            methods.append("_can_confirm_my_custom_rule")
            return methods
        """
        return [
            "_can_confirm_proper_state",
            "_can_confirm_has_lines",
            "_can_confirm_lines_have_product",
            "_can_confirm_analytic_distribution",
        ]

    def _can_confirm_proper_state(self):
        """Ensure orders are in draft state before confirmation."""
        orders_wrong_state = self.filtered(lambda order: order.state != "draft")
        if not orders_wrong_state:
            return
        confirmed_orders = orders_wrong_state.filtered(lambda o: o.state == "done")
        cancelled_orders = orders_wrong_state.filtered(lambda o: o.state == "cancel")
        error_parts = []
        if confirmed_orders:
            error_parts.append(
                _(
                    "• Already confirmed: %s",
                    format_list(self.env, confirmed_orders.mapped("display_name")),
                ),
            )
        if cancelled_orders:
            error_parts.append(
                _(
                    "• Cancelled: %s",
                    format_list(self.env, cancelled_orders.mapped("display_name")),
                ),
            )
        raise UserError(
            _(
                "Cannot confirm %(desc)s that are not in draft state:\n\n%(details)s",
                desc=self._description,
                details="\n".join(error_parts),
            ),
        )

    def _requires_lines_to_confirm(self):
        """Whether confirming this order requires it to carry at least one line.

        True for an ordinary order: confirming an empty one is a mistake, and the
        message says so.

        It is not universal, though, which is why this is a record-level predicate and
        not simply the absence of ``_can_confirm_has_lines`` from
        ``_get_can_confirm_validation_methods``. That list is per *model*, so dropping
        the validator to accommodate one flow would disable it for every order of that
        model. A flow that confirms empty on purpose overrides this instead, and only
        for the orders it owns -- ``industry_fsm_stock`` is the case in the tree: it
        confirms a field-service order before any material is on it, because
        confirmation is what binds the order and its pickings to the technician's
        warehouse.
        """
        self.ensure_one()
        return True

    def _can_confirm_has_lines(self):
        """Ensure orders have at least one order line."""
        orders_without_lines = self.filtered(
            lambda order: not order.line_ids and order._requires_lines_to_confirm()
        )
        if orders_without_lines:
            raise UserError(
                _(
                    "Cannot confirm %(desc)s without lines: %(orders)s\n\n"
                    "Please add at least one product line before confirming.",
                    desc=self._description,
                    orders=format_list(
                        self.env,
                        orders_without_lines.mapped("display_name"),
                    ),
                ),
            )

    def _can_confirm_lines_have_product(self):
        """Ensure all non-display, non-downpayment lines have a product."""
        orders_without_line_product = self.filtered(
            lambda order: any(
                not line.display_type
                and not line.is_downpayment
                and not line.product_id
                for line in order.line_ids
            ),
        )
        if not orders_without_line_product:
            return
        error_details = []
        for order in orders_without_line_product:
            missing_product_lines = order.line_ids.filtered(
                lambda l: (
                    not l.display_type and not l.is_downpayment and not l.product_id
                ),
            )
            error_details.append(
                _(
                    "• %(order)s has %(count)d line(s) without products",
                    order=order.display_name,
                    count=len(missing_product_lines),
                ),
            )
        raise UserError(
            _(
                "Cannot confirm %(desc)s with lines missing products:\n\n%(details)s\n\n"
                "Please assign a product to all order lines before confirming.",
                desc=self._description,
                details="\n".join(error_details),
            ),
        )

    def _can_confirm_analytic_distribution(self):
        """Validate analytic distributions.  Implementations differ — override."""

    # Cancel validation

    def _can_cancel(self):
        """Run all cancellation validations.

        :raises UserError: if any validation fails
        """
        for method_name in self._get_can_cancel_validation_methods():
            getattr(self, method_name)()

    def _get_can_cancel_validation_methods(self):
        """Return validator method names called by ``_can_cancel``.

        Purchase extends via ``super()`` to add ``_can_cancel_except_invoiced``.
        """
        return [
            "_can_cancel_check_state",
            "_can_cancel_except_locked",
        ]

    def _can_cancel_check_state(self):
        """Ensure orders are not already cancelled."""
        cancelled_orders = self.filtered(lambda order: order.state == "cancel")
        if cancelled_orders:
            raise UserError(
                _(
                    "The following %(desc)s are already cancelled: %(orders)s",
                    desc=self._description,
                    orders=format_list(
                        self.env,
                        cancelled_orders.mapped("display_name"),
                    ),
                ),
            )

    def _can_cancel_except_locked(self):
        """Ensure orders are not locked."""
        orders_locked = self.filtered(lambda order: order.locked)
        if orders_locked:
            raise UserError(
                _(
                    "Cannot cancel locked %(desc)s: %(orders)s. "
                    "Please unlock them first using the 'Unlock' button.",
                    desc=self._description,
                    orders=format_list(self.env, orders_locked.mapped("display_name")),
                ),
            )

    # ------------------------------------------------------------------
    # WORKFLOW ACTIONS
    # ------------------------------------------------------------------

    def action_confirm(self):
        """Confirm orders: validate → write state → post-confirm hook → auto-lock."""
        self._can_confirm()
        self.write(self._prepare_confirmation_values())
        self.with_context(self._get_confirmation_context())._action_confirm()
        self.filtered(lambda order: order._should_be_locked()).action_lock()
        return True

    def action_cancel(self):
        """Cancel orders: validate → perform cancellation."""
        self._can_cancel()
        return self._action_cancel()

    def action_draft(self):
        self.write({"state": "draft"})
        return True

    def action_lock(self):
        """Lock orders.  Purchase overrides to also reset priority."""
        self.write({"locked": True})
        return True

    def action_unlock(self):
        self.write({"locked": False})
        return True

    def action_acknowledge(self):
        """Mark the orders as acknowledged by the partner."""
        self.write({"acknowledged": True})

    def action_print_order(self):
        """Render the order's PDF and record the print.

        Both order types declare ``printed_before`` and ``count_print``, but
        only purchase ever wrote the first and nobody wrote the second: sale's
        Print button was wired straight to ``ir.actions.report``, so its own
        ``printed_before`` field could never become true. Routing both buttons
        through here is what makes the two fields mean the same thing on both
        models.
        """
        self._mark_as_printed()
        return self.env.ref(self._get_print_report_xmlid()).report_action(self)

    def _get_print_report_xmlid(self):
        """XML id of the report rendered by the Print button."""
        raise NotImplementedError(
            f"{self._name} must implement _get_print_report_xmlid()"
        )

    def _mark_as_printed(self):
        """Count a print, and flag draft orders as printed before.

        ``printed_before`` stays draft-only, matching the behaviour purchase
        already had: it answers "did this go out before it was confirmed".
        ``count_print`` counts every print.
        """
        for order in self:
            vals = {"count_print": order.count_print + 1}
            if order.state == "draft":
                vals["printed_before"] = True
            order.write(vals)

    def action_view_business_doc(self):
        self.ensure_one()
        return {
            "name": _("Order"),
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "views": [(False, "form")],
        }

    @api.model
    def get_import_templates(self):
        return [
            {
                "label": self._get_import_template_label(),
                "template": self._get_import_template_path(),
            },
        ]

    def _get_import_template_label(self):
        raise NotImplementedError(
            f"{self._name} must implement _get_import_template_label()"
        )

    def _get_import_template_path(self):
        raise NotImplementedError(
            f"{self._name} must implement _get_import_template_path()"
        )

    # ------------------------------------------------------------------
    # WRITE VALIDATIONS
    # ------------------------------------------------------------------

    def _check_write_guards(self, vals):
        """Run all registered write validators before persisting ``vals``."""
        for method_name in self._get_check_write_guards():
            getattr(self, method_name)(vals)

    def _get_check_write_guards(self):
        """Validator method names for write. Override to extend."""
        return [
            "_check_write_locked_order",
            "_check_write_state_frozen_fields",
            "_check_write_state_transition",
        ]

    def _get_fields_state_frozen(self):
        """Map of ``{state: {field names frozen in that state}}``.

        Empty by default; subclasses override (e.g. ``sale.order`` freezes
        ``pricelist_id`` in ``done``).
        """
        return {}

    def _check_write_locked_order(self, vals):
        """Freeze all user-editable business fields on locked orders.

        Whitelist model: only ``_LOCKED_WRITABLE_FIELDS`` may change while
        locked. Scoped over ``_get_fields_user_editable`` so framework writes
        (chatter, activities, stored-compute) are never blocked. Bypassable
        via the ``bypass_locked_check`` context key.
        """
        if self.env.context.get("bypass_locked_check"):
            return
        locked = self.filtered("locked")
        if not locked:
            return
        candidate = (
            set(vals) & locked._get_fields_user_editable()
        ) - self._LOCKED_WRITABLE_FIELDS
        if not candidate:
            return
        for order in locked:
            # Skip no-op re-writes (value unchanged): integration/ORM callers
            # that re-set a field to its current value must not be blocked.
            # Scalars and many2one are compared by value/id; x2many command
            # lists can't be cheaply compared, so they stay strict.
            forbidden = set()
            for name in candidate:
                field = order._fields[name]
                if field.type in ("many2many", "one2many"):
                    forbidden.add(name)
                    continue
                current = order[name]
                if field.type == "many2one":
                    current = current.id
                if current != vals[name]:
                    forbidden.add(name)
            if forbidden:
                raise UserError(
                    _(
                        "This order is locked and cannot be modified. "
                        "Unlock it first to change: %s",
                        order._get_field_labels(forbidden),
                    ),
                )

    def _get_fields_user_editable(self):
        """User-settable business fields.

        Excludes computed/display (readonly), related, and magic columns, so
        framework and computed writes fall outside the locked whitelist.
        """
        return {
            name
            for name, field in self._fields.items()
            if field.store
            and not field.related
            and not field.readonly
            and name not in MAGIC_COLUMNS
        }

    def _check_write_state_frozen_fields(self, vals):
        """Reject writes to fields frozen in the current *or* target state.

        Checking the target state as well closes the bypass where a single
        write sets both ``state`` and a field frozen in that new state
        (e.g. ``{"state": "done", "pricelist_id": X}`` on a draft order).
        """
        frozen_map = self._get_fields_state_frozen()
        changed = set(vals)
        target_state = vals.get("state")
        for order in self:
            relevant_states = {order.state, target_state} - {None}
            frozen = (
                set().union(
                    *(frozen_map.get(state, set()) for state in relevant_states),
                )
                & changed
            )
            if frozen:
                raise UserError(
                    _(
                        "You cannot modify %(fields)s on a %(state)s order.",
                        fields=order._get_field_labels(frozen),
                        state=target_state or order.state,
                    ),
                )

    def _check_write_state_transition(self, vals):
        """Reject illegal ``state`` transitions on raw writes."""
        if "state" not in vals:
            return
        target = vals["state"]
        for order in self:
            if order.state == target:
                continue  # no-op self-write
            if target not in self._STATE_TRANSITIONS.get(order.state, set()):
                raise UserError(
                    _(
                        "Cannot move order %(name)s from %(src)s to %(dst)s.",
                        name=order.display_name,
                        src=order.state,
                        dst=target,
                    ),
                )

    def _get_field_labels(self, field_names):
        """Comma-joined human field labels for ``field_names`` on this model."""
        fields_info = (
            self.env["ir.model.fields"]
            .sudo()
            .search(
                [
                    ("name", "in", list(field_names)),
                    ("model", "=", self._name),
                ],
            )
        )
        return ", ".join(fields_info.mapped("field_description")) or ", ".join(
            sorted(field_names),
        )

    # ------------------------------------------------------------------
    # INTERNAL WARNINGS
    # ------------------------------------------------------------------

    def _get_warning_group(self):
        """Security group gating internal warnings, or False to always show.

        Sale returns ``sale.group_warning_sale``, purchase
        ``purchase.group_warning_purchase``.
        """
        return False

    def _get_partner_warn_field(self):
        """``res.partner`` field carrying the internal warning, if any.

        Sale returns ``sale_warn_msg``, purchase ``purchase_warn_msg``.
        """
        return False

    def _get_line_warn_field(self):
        """Order-line field carrying the product's internal warning, if any.

        Sale returns ``sale_line_warn_msg``, purchase
        ``purchase_line_warn_msg``.
        """
        return False

    def _compute_warning_text(self, target_field):
        """Fill ``target_field`` with the partner's and products' warnings.

        The warning is built from three sources, de-duplicated and newline
        joined: the partner's own message, its commercial parent's, and one
        per order line whose product carries a message.

        Concrete models keep their own field (``sale_warning_text``,
        ``purchase_warning_text``) because the label and the ``@api.depends``
        differ; only the body is shared, via the three hooks above.
        """
        group = self._get_warning_group()
        if group and not self.env.user.has_group(group):
            setattr(self, target_field, "")
            return

        partner_field = self._get_partner_warn_field()
        line_field = self._get_line_warn_field()
        for order in self:
            warnings = OrderedSet()
            if partner_field:
                partner = order.partner_id
                for record in (partner, partner.parent_id):
                    if msg := record[partner_field]:
                        warnings.add(
                            (record.name or record.display_name) + " - " + msg,
                        )
            if line_field:
                for line in order.line_ids:
                    if msg := line[line_field]:
                        warnings.add(line.product_id.display_name + " - " + msg)
            setattr(order, target_field, "\n".join(warnings))

    # ------------------------------------------------------------------
    # DUPLICATE DETECTION
    # ------------------------------------------------------------------

    def _get_duplicate_ref_field(self):
        """Return the partner reference field used for duplicate matching.

        Sale overrides to return ``client_order_ref``.
        """
        return "partner_ref"

    def _get_duplicate_orders(self):
        """Fetch duplicated orders (same company/partner with matching refs).

        :return: mapping of order id to the set of duplicate order ids
        :rtype: dict
        """
        ref_field = self._get_duplicate_ref_field()
        orders = self.filtered(lambda order: order.id and order[ref_field])
        if not orders:
            return {}

        self.flush_model(["company_id", "partner_id", ref_field, "origin", "state"])

        # `o.state != 'cancel'` is a defensive guard, not a behavior change:
        # the sole caller (`_compute_duplicated_order_ids`) already filters to
        # draft orders before calling this method, but the method itself used
        # to trust that discipline instead of enforcing it — a future direct
        # caller passing confirmed/cancelled orders would have silently
        # gotten duplicate results for them too (t24068).
        result = self.env.execute_query(
            SQL(
                """
                SELECT o.id AS order_id,
                       array_agg(duplicate_order.id) AS duplicate_ids
                  FROM %(table)s o
                  JOIN %(table)s AS duplicate_order
                    ON o.company_id = duplicate_order.company_id
                   AND o.id != duplicate_order.id
                   AND duplicate_order.state != 'cancel'
                   AND o.partner_id = duplicate_order.partner_id
                   AND (
                        o.origin = duplicate_order.name
                        OR o.%(ref_field)s = duplicate_order.%(ref_field)s
                   )
                 WHERE o.id IN %(order_ids)s
                   AND o.state != 'cancel'
                 GROUP BY o.id
                """,
                table=SQL.identifier(self._table),
                ref_field=SQL.identifier(ref_field),
                order_ids=tuple(orders.ids),
            ),
        )
        return {order_id: set(duplicate_ids) for order_id, duplicate_ids in result}

    # ------------------------------------------------------------------
    # MAIL INTEGRATION
    # ------------------------------------------------------------------

    def _get_mark_sent_context_key(self):
        """Return the context key used to mark orders as sent during message_post.

        Sale: ``'mark_so_as_sent'``, Purchase: ``'mark_rfq_as_sent'``.
        """
        order_type = self._get_order_type()
        prefix = "so" if order_type == "sale" else "rfq"
        return f"mark_{prefix}_as_sent"

    def _mark_as_sent(self):
        """Flag orders as sent, and count the send.

        ``count_sent`` was declared on this mixin and written by nobody. The
        counter belongs next to the flag: ``sent`` only records that a send ever
        happened, and both order types re-send routinely (a revised quotation, a
        chased RFQ).
        """
        for order in self:
            order.with_context(**order._get_mark_as_sent_context()).write(
                {"sent": True, "count_sent": order.count_sent + 1},
            )

    def _get_mark_as_sent_context(self):
        """Extra context for the "mark as sent" write.

        Sale disables tracking here: its flow posts the outgoing mail to the
        chatter itself, so a tracked ``sent`` transition would double-log it.
        """
        return {}

    def message_post(self, **kwargs):
        """Mark draft orders as sent when the relevant context key is set."""
        mark_key = self._get_mark_sent_context_key()
        if self.env.context.get(mark_key):
            self.filtered(lambda order: order.state == "draft")._mark_as_sent()
            kwargs["notify_author_mention"] = kwargs.get("notify_author_mention", True)
        return super().message_post(**kwargs)

    def _get_mail_compose_form(self):
        """Return the standard mail composer form view id (or False)."""
        ir_model_data = self.env["ir.model.data"]
        try:
            compose_form_id = ir_model_data._xmlid_lookup(
                "mail.email_compose_message_wizard_form",
            )[1]
        except ValueError:
            compose_form_id = False
        return compose_form_id

    def _action_send_by_email(self):
        """Open the mail composer preloaded with this order's mail template.

        Sale's "Send" button and purchase's "Send RFQ" button opened the same
        wizard through two independently written actions. Everything that
        differed between them is a hook: the dialog title
        (``_get_mail_composer_action_name``), the composer context
        (``_get_mail_composer_context``) and the template
        (``_get_mail_template``).

        The window is opened in the language the template renders in, so the
        composer's "View..." button and ``model_description`` reach the partner
        translated. Sale never did this and silently ignored a template's own
        ``lang``; purchase did switch, but only *after* it had already read
        ``model_description`` off the untranslated recordset, so the one string
        the switch existed for was still built in the user's language. The
        language is resolved first here, and the strings that depend on it come
        from ``_get_mail_composer_lang_context`` on the switched recordset.

        :rtype: dict
        """
        ctx = self._get_mail_composer_context()
        lang = self._get_mail_composer_lang(ctx)
        # Only switch to a language we actually resolved: ``with_context(lang=None)``
        # would not restore the user's language, it would drop translations
        # entirely and render the strings below in the source language.
        order = self.with_context(lang=lang) if lang else self
        ctx.update(order._get_mail_composer_lang_context())
        if lang:
            ctx["lang"] = lang
        compose_form_id = self._get_mail_compose_form()
        return {
            "name": self._get_mail_composer_action_name(),
            "type": "ir.actions.act_window",
            "res_model": "mail.compose.message",
            "view_mode": "form",
            "views": [(compose_form_id, "form")],
            "view_id": compose_form_id,
            "target": "new",
            "context": ctx,
        }

    def _get_mail_composer_lang_context(self):
        """Composer context keys whose value is a string rendered for the partner.

        Called on a recordset already switched to the template's language, so
        anything built here is translated. Base adds nothing; purchase supplies
        ``model_description``.
        """
        return {}

    def _get_mail_composer_action_name(self):
        """Title of the mail composer dialog."""
        return _("Send")

    def _get_mail_composer_context(self):
        """Context the mail composer opens with.

        Several orders at once compose in ``mass_mail`` mode, which renders one
        template per record and therefore takes none of the single-order keys
        (they all describe *the* order being composed to).
        """
        ctx = {
            "default_model": self._name,
            "default_res_ids": self.ids,
            "default_composition_mode": "comment",
            "default_email_layout_xmlid": (
                "mail.mail_notification_layout_with_responsible_signature"
            ),
            "email_notification_allow_footer": True,
            "hide_mail_template_management_options": True,
        }
        if len(self) > 1:
            ctx["default_composition_mode"] = "mass_mail"
        else:
            ctx.update(self._get_mail_composer_single_context())
        return ctx

    def _get_mail_composer_single_context(self):
        """Composer context keys that only make sense for a single order.

        ``hide_default_template`` (set by sale's list-view server action) asks
        for a blank composer; the order still needs its portal token, since the
        user is about to hand-write a mail carrying the portal link.
        """
        self.ensure_one()
        ctx = {"force_email": True}
        if self.env.context.get("hide_default_template"):
            self._portal_ensure_token()
            return ctx
        if mail_template := self._get_mail_template():
            ctx["default_template_id"] = mail_template.id
            ctx[self._get_mark_sent_context_key()] = True
        return ctx

    def _get_mail_template(self):
        """Return the ``mail.template`` used when sending this order.

        Returns a **record**, not an id — ``account.move._get_mail_template``
        and ``account.move.send._get_default_mail_template_id`` call this
        generically.

        :rtype: recordset of `mail.template`
        """
        raise NotImplementedError(f"{self._name} must implement _get_mail_template()")

    def _get_mail_composer_lang(self, ctx):
        """Return the language the mail composer should open in.

        The template's own language wins when it defines one, so the "View..."
        button and ``model_description`` reach the partner in the language the
        template renders.

        The guard tests ``default_res_ids``: ``mail.compose.message`` carries
        ``res_ids``, and these composers set ``default_res_ids`` accordingly —
        but the test used to name the singular ``default_res_id``, so it never
        matched and the template language was silently never applied.
        """
        lang = self.env.context.get("lang")
        required = {"default_template_id", "default_model", "default_res_ids"}
        if not required <= ctx.keys():
            return lang
        res_ids = ctx["default_res_ids"]
        template = self.env["mail.template"].browse(ctx["default_template_id"])
        if res_ids and template.lang:
            lang = template._render_lang(res_ids)[res_ids[0]]
        return lang

    def _notify_by_email_prepare_rendering_context(
        self,
        message,
        msg_vals=False,
        model_description=False,
        force_email_company=False,
        force_email_lang=False,
        force_record_name=False,
        tracking_values=None,
    ):
        render_context = super()._notify_by_email_prepare_rendering_context(
            message,
            msg_vals=msg_vals,
            model_description=model_description,
            force_email_company=force_email_company,
            force_email_lang=force_email_lang,
            force_record_name=force_record_name,
            tracking_values=tracking_values,
        )
        render_context["subtitles"] = self._get_mail_subtitles(render_context)
        return render_context

    def _get_mail_subtitles(self, render_context):
        """Subtitles shown in notification emails.

        Sale shows name/partner and total; purchase shows name and due-date or
        total.  Base shows nothing; override per model.
        """
        return []

    def _notify_get_recipients_groups(
        self,
        message,
        model_description,
        msg_vals=False,
    ):
        groups = super()._notify_get_recipients_groups(
            message,
            model_description,
            msg_vals=msg_vals,
        )
        if not self:
            return groups
        self.ensure_one()
        self._tweak_notify_recipient_groups(groups)
        return groups

    def _tweak_notify_recipient_groups(self, groups):
        """Adjust portal access buttons on notification recipient groups.

        Sale sets sign/pay titles; purchase sets a confirm URL.  No-op by
        default; override per model.
        """
        return

    def _track_subtype(self, init_values):
        self.ensure_one()
        xmlid = self._get_state_track_subtype_xmlid(init_values)
        if xmlid:
            return self.env.ref(xmlid)
        return super()._track_subtype(init_values)

    def _get_state_track_subtype_xmlid(self, init_values):
        """Return the ``mail.message.subtype`` xmlid for a tracked change.

        Maps state/sent/locked transitions to a module subtype (e.g.
        ``sale.mt_order_confirmed``).  Returns a falsy value to defer to
        ``super()._track_subtype``.
        """
        return

    # ------------------------------------------------------------------
    # PORTAL
    # ------------------------------------------------------------------

    def _get_portal_url_prefix(self):
        """Return the ``/my/<prefix>`` portal URL prefix.

        Sale overrides to return ``'orders'``.
        """
        return self._get_order_type()

    def _compute_access_url(self):
        super()._compute_access_url()
        prefix = self._get_portal_url_prefix()
        for order in self:
            order.access_url = f"/my/{prefix}/{order.id}"

    def _get_report_base_filename(self):
        self.ensure_one()
        return f"{self.type_name} {self.name}"

    # ------------------------------------------------------------------
    # CATALOG INTEGRATION (mixin.product.catalog)
    # ------------------------------------------------------------------

    def _get_parent_field_on_child_model(self):
        return "order_id"

    def _default_order_line_values(self, child_field=False):
        default_data = super()._default_order_line_values(child_field)
        new_default_data = self.env[
            self._get_line_model()
        ]._get_product_catalog_lines_data()
        return {**default_data, **new_default_data}

    def _get_product_catalog_record_lines(
        self,
        product_ids,
        *,
        section_id=None,
        **kwargs,
    ):
        grouped_lines = defaultdict(lambda: self.env[self._get_line_model()])
        if section_id is None:
            section_id = (
                self.line_ids[:1].id
                if self.line_ids[:1].display_type == "line_section"
                else False
            )
        for line in self.line_ids:
            if (
                line.display_type
                or line.product_id.id not in product_ids
                or line.get_line_parent_section().id != section_id
            ):
                continue
            grouped_lines[line.product_id] |= line
        return grouped_lines

    def _get_action_add_from_catalog_extra_context(self):
        return {
            **super()._get_action_add_from_catalog_extra_context(),
            "product_catalog_currency_id": self.currency_id.id,
            "product_catalog_digits": self.line_ids._fields["price_unit"].get_digits(
                self.env,
            ),
            "show_sections": bool(self.id),
        }

    def _get_product_catalog_domain(self):
        return super()._get_product_catalog_domain() & Domain(
            self._get_catalog_product_ok_field(),
            "=",
            True,
        )

    def _get_catalog_product_ok_field(self):
        """Product boolean field gating catalog visibility.

        Sale → ``'sale_ok'``, purchase → ``'purchase_ok'``.
        """
        raise NotImplementedError(
            f"{self._name} must implement _get_catalog_product_ok_field()"
        )

    def _get_product_catalog_order_data(self, products, **kwargs):
        res = super()._get_product_catalog_order_data(products, **kwargs)
        catalog_data = self._get_catalog_product_data(products, **kwargs)
        for product in products:
            res[product.id].update(catalog_data.get(product.id, {}))
        return res

    def _get_catalog_product_data(self, products, **kwargs):
        """Per-product catalog payload merged into the order data.

        Returns ``{product_id: {...}}``.  Sale supplies pricelist price and
        warnings; purchase supplies seller price / packaging data.  Base adds
        nothing.
        """
        return {}

    def _update_order_line_info(
        self,
        product_id,
        quantity,
        *,
        section_id=False,
        child_field="line_ids",
        **kwargs,
    ):
        """Update the order line for a product/section or create a new one.

        :param int product_id: ``product.product`` id selected in the catalog.
        :param float quantity: quantity selected in the catalog.
        :param int section_id: id of the selected section, if any.
        :return: the discounted unit price for the product.
        :rtype: float
        """
        self.ensure_one()
        self._prepare_catalog_update()
        line = self.line_ids.filtered(
            lambda l: (
                l.product_id.id == product_id
                and l.get_line_parent_section().id == section_id
            ),
        )
        if line:
            if quantity != 0:
                line.product_qty = quantity
            elif self.state in self._get_catalog_editable_states():
                price_unit = self._get_catalog_removed_line_price(
                    line.product_id,
                    **kwargs,
                )
                line.unlink()
                return price_unit
            else:
                line.product_qty = 0
        elif quantity > 0:
            line = self.env[self._get_line_model()].create(
                {
                    "order_id": self.id,
                    "product_id": product_id,
                    "product_qty": quantity,
                    "sequence": self._get_new_line_sequence(child_field, section_id),
                },
            )
            self._catalog_on_line_created(line, **kwargs)
        else:  # quantity of 0, no line to update: return default price
            product = self.env["product.product"].browse(product_id)
            return self._get_catalog_removed_line_price(product, **kwargs)
        return self._get_catalog_line_price(line)

    def _prepare_catalog_update(self):
        """Hook run before a catalog line update.

        Sale sets a ``catalog_skip_tracking`` request context here.
        """
        return

    def _get_catalog_editable_states(self):
        """Order states in which a catalog quantity of 0 removes the line."""
        return {"draft"}

    def _get_catalog_removed_line_price(self, product, **kwargs):
        """Unit price returned when a catalog line is removed or absent."""
        raise NotImplementedError(
            f"{self._name} must implement _get_catalog_removed_line_price()"
        )

    def _get_catalog_line_price(self, line):
        """Discounted unit price of an existing/created catalog line."""
        raise NotImplementedError(
            f"{self._name} must implement _get_catalog_line_price()"
        )

    def _catalog_on_line_created(self, line, **kwargs):
        """Hook after a catalog line is created (e.g. purchase seller pricing)."""
        return line

    # ------------------------------------------------------------------
    # EDI / DOCUMENT IMPORT (mixin.account.document.import)
    # ------------------------------------------------------------------

    def _get_edi_builders(self):
        return []

    def create_document_from_attachment(self, attachment_ids):
        """Create orders from the given attachments and open them.

        Requires ``mixin.account.document.import`` on the concrete model.

        :param list attachment_ids: list of ``ir.attachment`` ids to process
        :return: an action redirecting to the created orders
        :rtype: dict
        """
        attachments = self.env["ir.attachment"].browse(attachment_ids)
        if not attachments:
            raise UserError(_("No attachment was provided."))

        orders = self.with_context(
            default_partner_id=self.env.user.partner_id.id,
        )._create_records_from_attachments(attachments)
        return orders._get_records_action(name=_("Generated Orders"))
