from collections import defaultdict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command
from odoo.tools import SQL, format_list


class OrderMixin(models.AbstractModel):
    """Base mixin for sale.order and purchase.order.

    Consolidates patterns that were duplicated across both modules.
    Child models implement ``_get_order_type()`` and override hooks
    for model-specific behaviour.

    Usage::

        class SaleOrder(models.Model):
            _name = "sale.order"
            _inherit = ["order.mixin", "order.amount.mixin", ...]

            def _get_order_type(self):
                return "sale"
    """

    _name = "order.mixin"
    _description = "Order Management Base"
    _inherit = [
        "mail.thread",
        "mail.activity.mixin",
        "portal.mixin",
        "product.catalog.mixin",
    ]

    # ------------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------------

    name = fields.Char(
        string="Order Reference",
        required=True,
        default=lambda self: _("New"),
        readonly=True,
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

    # Computed status helpers
    is_expired = fields.Boolean(
        string="Is Expired",
        compute="_compute_is_expired",
    )
    type_name = fields.Char(
        string="Type Name",
        compute="_compute_type_name",
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
        """Stub — child models override to select the sale/purchase journal."""
        self.journal_id = False

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

        Concrete models declare the ``duplicated_order_ids`` Many2many field
        (an abstract model cannot point a Many2many at its concrete model) and
        extend the dependencies with their reference field.
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

        Requires ``invoice_ids`` (provided by ``order.invoice.mixin``); the
        guard keeps this mixin usable standalone.
        """
        if "invoice_ids" in self._fields:
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
            if hasattr(self, method_name):
                getattr(self, method_name)()
            # Missing methods are skipped silently to allow gradual adoption.

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

    def _can_confirm_has_lines(self):
        """Ensure orders have at least one order line."""
        orders_without_lines = self.filtered(lambda order: not order.line_ids)
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
            if hasattr(self, method_name):
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
        """Flag orders as sent.  Sale overrides to disable tracking."""
        self.write({"sent": True})

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
    # CATALOG INTEGRATION (product.catalog.mixin)
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

    # ------------------------------------------------------------------
    # EDI / DOCUMENT IMPORT (account.document.import.mixin)
    # ------------------------------------------------------------------

    def _get_edi_builders(self):
        return []

    def create_document_from_attachment(self, attachment_ids):
        """Create orders from the given attachments and open them.

        Requires ``account.document.import.mixin`` on the concrete model.

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
