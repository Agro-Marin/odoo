from datetime import timedelta
from itertools import groupby
import json

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Command
from odoo.orm.utils import SUPERUSER_ID
from odoo.tools import format_amount, format_date, format_list, is_html_empty
from odoo.tools.float_utils import float_is_zero
from odoo.tools.mail import html_keep_url
from odoo.tools.translate import _

from odoo.addons.payment import utils as payment_utils

SALE_ORDER_STATE = [
    ("draft", "Quotation"),
    ("sale", "Sales Order"),
    ("cancel", "Cancelled"),
]

INVOICE_STATE = [
    ("no", "Nothing to invoice"),
    ("to do", "To invoice"),
    ("partially", "Partially invoiced"),
    ("upselling", "Upselling Opportunity"),
    ("done", "Fully invoiced"),
    ("over done", "Upselling"),
]


class SaleOrder(models.Model):
    """Management the sales order process from quotation to confirmation and invoicing.

    Handles customer sales transactions, including pricing, payment terms, delivery methods,
    and order lifecycle management."""

    _name = "sale.order"
    _inherit = [
        "mail.activity.mixin",
        "mail.thread",
        "portal.mixin",
        "utm.mixin",
    ]
    _description = "Sales Order"
    _order = "date_order desc, id desc"
    _check_company_auto = True
    _mail_thread_customer = True

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    country_code = fields.Char(
        related="company_id.account_fiscal_country_id.code",
        string="Country code",
    )
    company_price_include = fields.Selection(
        related="company_id.account_price_include",
    )
    tax_calculation_rounding_method = fields.Selection(
        related="company_id.tax_calculation_rounding_method",
        depends=["company_id"],
        string="Tax calculation rounding method",
        readonly=True,
    )
    terms_type = fields.Selection(
        related="company_id.terms_type",
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Customer",
        required=True,
        change_default=True,
        check_company=True,
        tracking=1,
        index=True,
    )
    partner_invoice_id = fields.Many2one(
        comodel_name="res.partner",
        string="Invoice Address",
        required=True,
        compute="_compute_partner_invoice_id",
        store=True,
        precompute=True,
        readonly=False,
        check_company=True,
        index="btree_not_null",
    )
    partner_shipping_id = fields.Many2one(
        comodel_name="res.partner",
        string="Delivery Address",
        required=True,
        compute="_compute_partner_shipping_id",
        store=True,
        precompute=True,
        readonly=False,
        check_company=True,
        index="btree_not_null",
    )
    fiscal_position_id = fields.Many2one(
        comodel_name="account.fiscal.position",
        string="Fiscal Position",
        compute="_compute_fiscal_position_id",
        store=True,
        precompute=True,
        readonly=False,
        domain='[("company_id", "in", (False, company_id))]',
        help="Fiscal positions are used to adapt taxes and accounts for particular customers or "
        "sales orders/invoices. The default value comes from the customer.",
    )
    tax_country_id = fields.Many2one(
        comodel_name="res.country",
        compute="_compute_tax_country_id",
        compute_sudo=True,
    )
    pricelist_id = fields.Many2one(
        comodel_name="product.pricelist",
        string="Pricelist",
        compute="_compute_pricelist_id",
        store=True,
        precompute=True,
        readonly=False,
        check_company=True,  # Unrequired company
        domain="[('company_id', 'in', (False, company_id))]",
        tracking=1,
        help="If you change the pricelist, only newly added lines will be affected.",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        required=True,
        compute="_compute_currency_id",
        store=True,
        precompute=True,
        ondelete="restrict",
    )
    currency_rate = fields.Float(
        string="Currency Rate",
        digits=0,
        compute="_compute_currency_rate",
        store=True,
        precompute=True,
    )
    payment_term_id = fields.Many2one(
        comodel_name="account.payment.term",
        string="Payment Terms",
        compute="_compute_payment_term_id",
        store=True,
        precompute=True,
        readonly=False,
        domain="[('company_id', 'in', (False, company_id))]",
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Salesperson",
        compute="_compute_user_id",
        store=True,
        precompute=True,
        readonly=False,
        domain=lambda self: """
            [
                ('all_group_ids', 'in', {}),
                ('share', '=', False),
                ('company_ids', '=', company_id)
            ]
        """.format(
            self.env.ref("sales_team.group_sale_salesman").ids
        ),
        tracking=2,
        index=True,
    )
    team_id = fields.Many2one(
        comodel_name="crm.team",
        string="Sales Team",
        compute="_compute_team_id",
        store=True,
        precompute=True,
        readonly=False,
        change_default=True,
        check_company=True,  # Unrequired company
        domain="[('company_id', 'in', (False, company_id))]",
        ondelete="set null",
        tracking=True,
    )
    journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Invoicing Journal",
        compute="_compute_journal_id",
        store=True,
        precompute=True,
        readonly=False,
        check_company=True,
        domain=[("type", "=", "sale")],
        help="If set, the SO will invoice in this journal; "
        "otherwise the sales journal with the lowest sequence is used.",
    )
    name = fields.Char(
        string="Order Reference",
        required=True,
        default=lambda self: _("New"),
        readonly=True,
        copy=False,
        index="trigram",
    )
    approval_request_id = fields.Many2one(
        comodel_name="approval.request",
        string="Approval",
        copy=False,
    )
    approval_state = fields.Char(
        compute="_compute_approval_state",
    )
    state = fields.Selection(
        selection=SALE_ORDER_STATE,
        string="Status",
        default="draft",
        readonly=True,
        copy=False,
        tracking=3,
        index=True,
    )
    priority = fields.Selection(
        [
            ("0", "Normal"),
            ("1", "Urgent"),
        ],
        string="Priority",
        default="0",
        index=True,
    )
    locked = fields.Boolean(
        default=False,
        copy=False,
        tracking=True,
        help="Locked orders cannot be modified.",
    )
    sent = fields.Boolean(
        default=False,
        copy=False,
        tracking=True,
        help="THE Quotation has been sent to the customer.",
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
        help="THE RFQ has already been printed.",
    )
    count_print = fields.Integer(
        string="Print Count",
        default=0,
        copy=False,
    )
    create_date = fields.Datetime(
        string="Creation Date",
        readonly=True,
        index=True,
    )
    date_order = fields.Datetime(
        string="Order Date",
        required=True,
        default=fields.Datetime.now,
        copy=False,
        help="Creation date of draft/sent orders,\nConfirmation date of confirmed orders.",
    )
    date_validity = fields.Date(
        string="Expiration",
        compute="_compute_date_validity",
        store=True,
        precompute=True,
        readonly=False,
        copy=False,
        help="Validity of the order, after that you will not able to sign & pay the quotation.",
    )
    date_commitment = fields.Datetime(
        string="Delivery Date",
        copy=False,
        help="This is the delivery date promised to the customer. "
        "If set, the delivery order will be scheduled based on "
        "this date rather than product lead times.",
    )
    date_planned = fields.Datetime(
        string="Expected Date",
        compute="_compute_date_planned",
        store=False,  # Note: can not be stored since depends on today()
        help="Delivery date you can promise to the customer, computed from "
        "the minimum lead time of the order lines.",
    )
    date_approve = fields.Datetime(
        string="Approval Date",
        readonly=True,
        copy=False,
        index=True,
    )
    origin = fields.Char(
        string="Source",
        copy=False,
        help="Reference of the document that generated this sales order request",
    )
    client_order_ref = fields.Char(
        string="Customer Reference",
        copy=False,
    )
    partner_ref = fields.Char(
        string="Vendor Reference",
        copy=False,
        help="Reference of the sales order or bid sent by the vendor. "
        "It's used to do the matching when you receive the "
        "products as this reference is usually written on the "
        "delivery order sent by your vendor.",
    )
    reference = fields.Char(
        string="Payment Ref.",
        copy=False,
        help="The payment communication of this sale order.",
    )
    notes = fields.Html(
        string="Terms and conditions",
        compute="_compute_notes",
        store=True,
        precompute=True,
        readonly=False,
    )

    # Signature block
    require_signature = fields.Boolean(
        string="Online signature",
        compute="_compute_require_signature",
        store=True,
        precompute=True,
        readonly=False,
        help="Request a online signature from the customer to confirm the order.",
    )
    signature = fields.Image(
        string="Signature",
        copy=False,
        attachment=True,
        max_width=1024,
        max_height=1024,
    )
    signed_by = fields.Char(string="Signed By", copy=False)
    signed_on = fields.Datetime(string="Signed On", copy=False)

    # Payment block
    require_payment = fields.Boolean(
        string="Online payment",
        compute="_compute_require_payment",
        store=True,
        precompute=True,
        readonly=False,
        help="Request a online payment from the customer to confirm the order.",
    )
    prepayment_percent = fields.Float(
        string="Prepayment percentage",
        compute="_compute_prepayment_percent",
        store=True,
        precompute=True,
        readonly=False,
        help="The percentage of the amount needed that must be paid by the customer to confirm the order.",
    )

    # Order line block
    line_ids = fields.One2many(
        comodel_name="sale.order.line",
        inverse_name="order_id",
        string="Order Lines",
        copy=True,
        auto_join=True,
    )
    product_id = fields.Many2one(
        related="line_ids.product_id",
        string="Product",
    )
    amount_untaxed = fields.Monetary(
        string="Untaxed Amount",
        compute="_compute_amounts",
        store=True,
        readonly=True,
        tracking=5,
    )
    amount_tax = fields.Monetary(
        string="Taxes",
        compute="_compute_amounts",
        store=True,
        readonly=True,
        tracking=4,
    )
    amount_total = fields.Monetary(
        string="Total",
        compute="_compute_amounts",
        store=True,
        readonly=True,
        tracking=4,
    )
    amount_undiscounted = fields.Float(
        string="Amount Before Discount",
        digits=0,
        compute="_compute_amount_undiscounted",
    )
    tax_totals = fields.Binary(
        compute="_compute_tax_totals",
        exportable=False,
    )

    # Invoice block
    invoice_ids = fields.Many2many(
        comodel_name="account.move",
        string="Invoices",
        compute="_compute_invoice_ids",
        search="_search_invoice_ids",
        copy=False,
    )
    count_invoice_ids = fields.Integer(
        string="Invoice Count",
        compute="_compute_invoice_ids",
    )
    amount_to_invoice_taxinc = fields.Monetary(
        string="Un-invoiced Balance",
        compute="_compute_amount_invoiced",
    )
    amount_invoiced_taxinc = fields.Monetary(
        string="Already invoiced",
        compute="_compute_amount_invoiced",
    )
    invoice_state = fields.Selection(
        selection=INVOICE_STATE,
        string="Invoice Status",
        default="no",
        compute="_compute_invoice_state",
        store=True,
        readonly=True,
        copy=False,
    )

    # Transaction block
    transaction_ids = fields.Many2many(
        comodel_name="payment.transaction",
        relation="sale_order_transaction_rel",
        column1="sale_order_id",
        column2="transaction_id",
        string="Transactions",
        copy=False,
        readonly=True,
    )
    authorized_transaction_ids = fields.Many2many(
        comodel_name="payment.transaction",
        string="Authorized Transactions",
        compute="_compute_authorized_transaction_ids",
        compute_sudo=True,
        copy=False,
    )
    amount_paid = fields.Float(
        string="Payment Transactions Amount",
        compute="_compute_amount_paid",
        compute_sudo=True,
        help="Sum of transactions made in through the online payment form that are in the state"
        " 'done' or 'authorized' and linked to this order.",
    )

    # UTMs - enforcing the fact that we want to "set null" when relation is unlinked
    campaign_id = fields.Many2one(ondelete="set null")
    medium_id = fields.Many2one(ondelete="set null")
    source_id = fields.Many2one(ondelete="set null")

    tag_ids = fields.Many2many(
        comodel_name="crm.tag",
        relation="sale_order_tag_rel",
        column1="order_id",
        column2="tag_id",
        string="Tags",
    )
    type_name = fields.Char(
        string="Type Name",
        compute="_compute_type_name",
    )
    partner_credit_warning = fields.Text(
        compute="_compute_partner_credit_warning",
    )
    is_expired = fields.Boolean(
        string="Is Expired",
        compute="_compute_is_expired",
    )
    has_archived_products = fields.Boolean(
        compute="_compute_has_archived_products",
    )
    has_active_pricelist = fields.Boolean(
        compute="_compute_has_active_pricelist",
    )
    show_update_fpos = fields.Boolean(
        string="Has Fiscal Position Changed",
        store=False,
        # True if the fiscal position was changed
    )
    show_update_pricelist = fields.Boolean(
        string="Has Pricelist Changed",
        store=False,
        # True if the pricelist was changed
    )

    # ------------------------------------------------------------
    # CONSTRAINTS
    # ------------------------------------------------------------

    _date_order_conditional_required = models.Constraint(
        "CHECK((state = 'sale' AND date_order IS NOT NULL) OR state != 'sale')",
        "A confirmed sales order requires a confirmation date.",
    )

    @api.constrains("company_id", "line_ids")
    def _check_order_line_company_id(self):
        for order in self:
            invalid_companies = order.line_ids.product_id.company_id.filtered(
                lambda c: order.company_id not in c._accessible_branches()
            )
            if invalid_companies:
                bad_products = order.line_ids.product_id.filtered(
                    lambda p: p.company_id and p.company_id in invalid_companies
                )
                raise ValidationError(
                    _(
                        "Your quotation contains products from company %(product_company)s "
                        "whereas your quotation belongs to company %(quote_company)s. \n"
                        "Please change the company of your quotation or remove the products "
                        "from other companies (%(bad_products)s).",
                        product_company=", ".join(
                            invalid_companies.sudo().mapped("display_name")
                        ),
                        quote_company=order.company_id.display_name,
                        bad_products=", ".join(bad_products.mapped("display_name")),
                    )
                )

    @api.constrains("prepayment_percent")
    def _check_prepayment_percent(self):
        for order in self:
            if order.require_payment and not (0 < order.prepayment_percent <= 1.0):
                raise ValidationError(
                    _("Prepayment percentage must be a valid percentage.")
                )

    # ------------------------------------------------------------
    # CRUD METHODS
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            company_id = vals.get(
                "company_id", self.default_get(["company_id"])["company_id"]
            )
            # Ensures default picking type and currency are taken from the right company.
            self_comp = self.with_company(company_id)
            if vals.get("name", _("New")) == _("New"):
                date_order = vals.get(
                    "date_order", self_comp.default_get(["date_order"])["date_order"]
                )
                seq_date = fields.Datetime.context_timestamp(
                    self_comp, fields.Datetime.to_datetime(date_order)
                )
                vals["name"] = self_comp.env["ir.sequence"].next_by_code(
                    "sale.order", sequence_date=seq_date
                )
        return super().create(vals_list)

    def write(self, vals):
        if "pricelist_id" in vals and any(order.state == "sale" for order in self):
            raise UserError(_("You cannot change the pricelist of a confirmed order !"))

        res = super().write(vals)

        if vals.get("partner_id"):
            self.filtered(lambda order: order.state == "sale").message_subscribe(
                partner_ids=[vals["partner_id"]],
            )

        return res

    def copy_data(self, default=None):
        default = dict(default or {})
        default_has_no_order_line = "line_ids" not in default
        default.setdefault("line_ids", [])
        vals_list = super().copy_data(default=default)
        if default_has_no_order_line:
            for order, vals in zip(self, vals_list):
                vals["line_ids"] = [
                    Command.create(line_vals)
                    for line_vals in order._get_order_lines_copiable().copy_data()
                ]
        return vals_list

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft_or_cancel(self):
        for order in self:
            if order.state not in ("draft", "cancel"):
                raise UserError(
                    _(
                        "You can not delete a confirmed sales order."
                        " You must first cancel it."
                    )
                )

    # base override
    @api.model
    def get_empty_list_help(self, help_msg):
        self = self.with_context(
            empty_list_help_document_name=_("sale order"),
        )
        return super().get_empty_list_help(help_msg)

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    # models.Model override
    def _compute_field_value(self, field):
        if field.name != "invoice_state" or self.env.context.get(
            "mail_activity_automation_skip"
        ):
            return super()._compute_field_value(field)

        filtered_self = self.filtered(
            lambda so: so.ids
            and (so.user_id or so.partner_id.user_id)
            and so._origin.invoice_state != "over done"
        )
        super()._compute_field_value(field)

        upselling_orders = filtered_self.filtered(
            lambda so: so.invoice_state == "over done"
        )
        upselling_orders._create_upsell_activity()

    # portal.mixin override
    def _compute_access_url(self):
        super()._compute_access_url()
        for order in self:
            order.access_url = f"/my/orders/{order.id}"

    def _compute_amount_undiscounted(self):
        for order in self:
            total = 0.0
            for line in order.line_ids:
                total += (
                    (line.price_subtotal * 100) / (100 - line.discount)
                    if line.discount != 100
                    else (line.price_unit * line.product_uom_qty)
                )
            order.amount_undiscounted = total

    def _compute_is_expired(self):
        today = fields.Date.today()
        for order in self:
            order.is_expired = (
                order.state == "draft"
                and order.date_validity
                and order.date_validity < today
            )

    def _compute_journal_id(self):
        self.journal_id = False

    @api.depends("company_id")
    def _compute_date_validity(self):
        today = fields.Date.context_today(self)
        for order in self:
            days = order.company_id.quotation_validity_days
            if days > 0:
                order.date_validity = today + timedelta(days)
            else:
                order.date_validity = False

    @api.depends("company_id")
    def _compute_has_active_pricelist(self):
        for order in self:
            order.has_active_pricelist = bool(
                self.env["product.pricelist"].search(
                    [
                        ("company_id", "in", (False, order.company_id.id)),
                        ("active", "=", True),
                    ],
                    limit=1,
                )
            )

    @api.depends("company_id")
    def _compute_require_payment(self):
        for order in self:
            order.require_payment = order.company_id.portal_confirmation_pay

    @api.depends("company_id")
    def _compute_require_signature(self):
        for order in self:
            order.require_signature = order.company_id.portal_confirmation_sign

    @api.depends("state")
    def _compute_type_name(self):
        for order in self:
            if order.state in ("draft", "cancel"):
                order.type_name = _("Quotation")
            else:
                order.type_name = _("Sale Order")

    @api.depends("require_payment")
    def _compute_prepayment_percent(self):
        for order in self:
            order.prepayment_percent = order.company_id.prepayment_percent

    @api.depends("approval_request_id")
    def _compute_approval_state(self):
        for order in self:
            if order.approval_request_id:
                order.approval_state = order.approval_request_id.state
            else:
                order.approval_state = "none"

    @api.depends_context("sale_show_partner_name")
    @api.depends("partner_id")
    def _compute_display_name(self):
        if not self._context.get("sale_show_partner_name"):
            return super()._compute_display_name()

        for order in self:
            name = order.name
            if order.partner_id.name:
                name = f"{name} - {order.partner_id.name}"
            order.display_name = name

    @api.depends("partner_id")
    def _compute_notes(self):
        use_invoice_terms = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("account.use_invoice_terms")
        )
        if not use_invoice_terms:
            return

        for order in self:
            order = order.with_company(order.company_id)
            if order.terms_type == "html" and self.env.company.invoice_terms_html:
                baseurl = html_keep_url(order._get_note_url() + "/terms")
                context = {"lang": order.partner_id.lang or self.env.user.lang}
                order.notes = _("Terms & Conditions: %s", baseurl)
                del context
            elif not is_html_empty(self.env.company.invoice_terms):
                if order.partner_id.lang:
                    order = order.with_context(lang=order.partner_id.lang)
                order.notes = order.env.company.invoice_terms

    @api.depends("partner_id")
    def _compute_partner_invoice_id(self):
        for order in self:
            order.partner_invoice_id = (
                order.partner_id.address_get(["invoice"])["invoice"]
                if order.partner_id
                else False
            )

    @api.depends("partner_id")
    def _compute_partner_shipping_id(self):
        for order in self:
            order.partner_shipping_id = (
                order.partner_id.address_get(["delivery"])["delivery"]
                if order.partner_id
                else False
            )

    @api.depends("partner_id")
    def _compute_payment_term_id(self):
        for order in self:
            order = order.with_company(order.company_id)
            order.payment_term_id = order.partner_id.property_payment_term_id

    @api.depends("partner_id")
    def _compute_user_id(self):
        for order in self:
            if order.partner_id and not (order._origin.id and order.user_id):
                # Recompute the salesman on partner change
                #   * if partner is set (is required anyway, so it will be set sooner or later)
                #   * if the order is not saved or has no salesman already
                order.user_id = (
                    order.partner_id.sale_user_id
                    or order.partner_id.commercial_partner_id.sale_user_id
                    or (
                        self.env.user.has_group("sales_team.group_sale_salesman")
                        and self.env.user
                    )
                )

    @api.depends("company_id", "partner_id")
    def _compute_pricelist_id(self):
        for order in self:
            if order.state != "draft":
                continue

            if not order.partner_id:
                order.pricelist_id = False
                continue

            order = order.with_company(order.company_id)
            order.pricelist_id = order.partner_id.property_product_pricelist

    @api.depends("company_id", "pricelist_id")
    def _compute_currency_id(self):
        for order in self:
            order.currency_id = (
                order.pricelist_id.currency_id or order.company_id.currency_id
            )

    @api.depends("company_id", "currency_id", "date_order")
    def _compute_currency_rate(self):
        for order in self:
            order.currency_rate = self.env["res.currency"]._get_conversion_rate(
                from_currency=order.company_id.currency_id,
                to_currency=order.currency_id,
                company=order.company_id,
                date=(order.date_order or fields.Datetime.now()).date(),
            )

    @api.depends("company_id", "partner_id", "partner_shipping_id")
    def _compute_fiscal_position_id(self):
        """Trigger the change of fiscal position when the shipping address is modified."""
        cache = {}
        for order in self:
            if not order.partner_id:
                order.fiscal_position_id = False
                continue

            fpos_id_before = order.fiscal_position_id.id
            key = (
                order.company_id.id,
                order.partner_id.id,
                order.partner_shipping_id.id,
            )
            if key not in cache:
                cache[key] = (
                    self.env["account.fiscal.position"]
                    .with_company(order.company_id)
                    ._get_fiscal_position(order.partner_id, order.partner_shipping_id)
                    .id
                )
            if fpos_id_before != cache[key] and order.line_ids:
                order.show_update_fpos = True
            order.fiscal_position_id = cache[key]

    @api.depends("company_id", "fiscal_position_id")
    def _compute_tax_country_id(self):
        for order in self:
            if order.fiscal_position_id.foreign_vat:
                order.tax_country_id = order.fiscal_position_id.country_id
            else:
                order.tax_country_id = order.company_id.account_fiscal_country_id

    @api.depends("partner_id", "user_id")
    def _compute_team_id(self):
        cached_teams = {}
        for order in self:
            default_team_id = (
                self.env.context.get("default_team_id", False) or order.team_id.id
            )
            user_id = order.user_id.id
            company_id = order.company_id.id
            key = (default_team_id, user_id, company_id)
            if key not in cached_teams:
                cached_teams[key] = (
                    self.env["crm.team"]
                    .with_context(
                        default_team_id=default_team_id,
                    )
                    ._get_default_team_id(
                        user_id=user_id,
                        domain=self.env["crm.team"]._check_company_domain(company_id),
                    )
                )
            order.team_id = cached_teams[key]

    @api.depends("line_ids.product_id")
    def _compute_has_archived_products(self):
        for order in self:
            order.has_archived_products = any(
                not product.active for product in order.line_ids.product_id
            )

    @api.depends("state", "date_order", "line_ids.customer_lead")
    def _compute_date_planned(self):
        """For service and consumable, we only take the min dates. This method is extended in sale_stock to
        take the picking_policy of SO into account."""
        self.mapped("line_ids")  # Prefetch indication
        for order in self:
            if order.state == "cancel":
                order.date_planned = False
                continue

            dates_list = order.line_ids.filtered(
                lambda line: not line.display_type and not line._is_delivery()
            ).mapped(lambda line: line and line._get_date_planned())
            if dates_list:
                order.date_planned = order._get_date_planned(dates_list)
            else:
                order.date_planned = False

    @api.depends(
        "company_id", "currency_id", "payment_term_id", "line_ids.price_subtotal"
    )
    def _compute_amounts(self):
        AccountTax = self.env["account.tax"]
        for order in self:
            order_lines = order.line_ids.filtered(lambda line: not line.display_type)
            base_lines = [
                line._prepare_base_line_for_taxes_computation() for line in order_lines
            ]
            base_lines += order._add_base_lines_for_early_payment_discount()
            AccountTax._add_tax_details_in_base_lines(base_lines, order.company_id)
            AccountTax._round_base_lines_tax_details(base_lines, order.company_id)
            tax_totals = AccountTax._get_tax_totals_summary(
                base_lines=base_lines,
                currency=order.currency_id or order.company_id.currency_id,
                company=order.company_id,
            )
            order.amount_untaxed = tax_totals["base_amount_currency"]
            order.amount_tax = tax_totals["tax_amount_currency"]
            order.amount_total = tax_totals["total_amount_currency"]

    @api.depends_context("lang")
    @api.depends(
        "company_id", "currency_id", "payment_term_id", "line_ids.price_subtotal"
    )
    def _compute_tax_totals(self):
        AccountTax = self.env["account.tax"]
        for order in self:
            order_lines = order.line_ids.filtered(lambda line: not line.display_type)
            base_lines = [
                line._prepare_base_line_for_taxes_computation() for line in order_lines
            ]
            base_lines += order._add_base_lines_for_early_payment_discount()
            AccountTax._add_tax_details_in_base_lines(base_lines, order.company_id)
            AccountTax._round_base_lines_tax_details(base_lines, order.company_id)
            order.tax_totals = AccountTax._get_tax_totals_summary(
                base_lines=base_lines,
                currency=order.currency_id or order.company_id.currency_id,
                company=order.company_id,
            )

    @api.depends("company_id", "partner_id", "amount_total")
    def _compute_partner_credit_warning(self):
        for order in self:
            order.with_company(order.company_id)
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

    @api.depends("line_ids.invoice_line_ids")
    def _compute_invoice_ids(self):
        # The invoice_ids are obtained thanks to the invoice lines of the SO
        # lines, and we also search for possible refunds created directly from
        # existing invoices. This is necessary since such a refund is not
        # directly linked to the SO.
        for order in self:
            invoices = order.line_ids.invoice_line_ids.move_id.filtered(
                lambda r: r.move_type in ("out_invoice", "out_refund")
            )
            order.invoice_ids = invoices
            order.count_invoice_ids = len(invoices)

    @api.depends("state", "line_ids.invoice_state", "invoice_ids")
    def _compute_invoice_state(self):
        """Compute the invoice status of a SO. Possible statuses:
        - no: If the SO is not in status 'sale' or 'done', we consider that there is nothing to
          invoice. This is also the default value if all lines are in 'no' state.
        - to do: If any SO line is 'to invoice', the whole SO is 'to invoice'.
        - partially: If some SO lines are invoiced and others are pending, the SO is 'partially invoiced'.
        - done: If all SO lines are in 'no' or 'done' state, and at least one is 'done', the SO is 'fully invoiced'.
        - over done: If all SO lines are invoiced and at least one is 'over invoiced', the status is 'over invoiced'.
        - upselling: If all SO lines are invoiced or upselling, the status is 'upselling'.
        """
        # Set default status for non-confirmed orders
        confirmed_orders = self.filtered(lambda o: o.state == "sale")
        (self - confirmed_orders).invoice_state = "no"

        if not confirmed_orders:
            return

        # Define domain to filter relevant lines
        lines_domain = [
            ("is_downpayment", "=", False),
            ("display_type", "=", False),
        ]
        # Get grouped invoice states for all confirmed orders
        line_invoice_state_all = {}
        for order, invoice_state in self.env["sale.order.line"]._read_group(
            lines_domain + [("order_id", "in", confirmed_orders.ids)],
            ["order_id", "invoice_state"],
        ):
            if not order.id in line_invoice_state_all:
                line_invoice_state_all[order.id] = set()
            line_invoice_state_all[order.id].add(invoice_state)
        # Process each confirmed order
        for order in confirmed_orders:
            states = line_invoice_state_all[order._origin.id]
            # If any line is 'to do', the whole order is 'to do'
            if any(state == "to do" for state in states):
                # Special case: check if only discount/delivery/promotion lines can be invoiced
                if any(state == "no" for state in states):
                    invoiceable_domain = lines_domain + [
                        ("invoice_state", "=", "to do")
                    ]
                    invoiceable_lines = order.line_ids.filtered_domain(
                        invoiceable_domain
                    )
                    special_lines = invoiceable_lines.filtered(
                        lambda sol: not sol._can_be_invoiced_alone()
                    )
                    # If only special lines can be invoiced, the order is not invoiceable
                    if invoiceable_lines == special_lines:
                        order.invoice_state = "no"
                    else:
                        order.invoice_state = "to do"
                else:
                    order.invoice_state = "to do"
            elif not order.invoice_ids or all(state == "to do" for state in states):
                order.invoice_state = "to do"
            # If any line us 'over done', the order is 'over done'
            elif any(state == "over done" for state in states):
                order.invoice_state = "over done"
            # If all lines are 'done' or 'upselling' and at least one is 'upselling', the order is 'upselling'
            elif all(state in ("done", "upselling") for state in states):
                if any(state == "upselling" for state in states):
                    order.invoice_state = "upselling"
                # If all lines are 'done' the order is fully invoiced
                else:
                    order.invoice_state = "done"
            # If any line is 'partially', the whole order is 'partially' invoiced
            elif any(state == "partially" for state in states) or (
                not any(state == "partially" for state in states)
                and any(state in ("to do", "done") for state in states)
            ):
                order.invoice_state = "partially"
            # Default status if no other conditions are met
            else:
                order.invoice_state = "no"

    @api.depends(
        "line_ids.amount_to_invoice_taxinc",
        "line_ids.amount_invoiced_taxinc",
    )
    def _compute_amount_invoiced(self):
        for order in self:
            order.amount_to_invoice_taxinc = sum(
                order.line_ids.mapped("amount_to_invoice_taxinc")
            )
            order.amount_invoiced_taxinc = sum(
                order.line_ids.mapped("amount_invoiced_taxinc")
            )

    @api.depends("transaction_ids")
    def _compute_authorized_transaction_ids(self):
        for trans in self:
            trans.authorized_transaction_ids = trans.transaction_ids.filtered(
                lambda t: t.state == "authorized"
            )

    @api.depends("transaction_ids")
    def _compute_amount_paid(self):
        """Sum of the amount paid through all transactions for this SO."""
        for order in self:
            order.amount_paid = sum(
                tx.amount
                for tx in order.transaction_ids
                if tx.state in ("authorized", "done")
            )

    # ------------------------------------------------------------
    # ONCHANGE METHODS
    # ------------------------------------------------------------

    def onchange(self, values, field_names, fields_spec):
        self_with_context = self
        if (
            not field_names
        ):  # Some warnings should not be displayed for the first onchange
            self_with_context = self.with_context(sale_onchange_first_call=True)
        return super(SaleOrder, self_with_context).onchange(
            values, field_names, fields_spec
        )

    @api.onchange("company_id")
    def _onchange_company_id(self):
        for order in self:
            # This can't be caught by a python constraint as it is only triggered at save
            # and a compute methodd needs this data to be set correctly before saving
            if not order.company_id:
                raise ValidationError(
                    _(
                        "The company is required, please select one before making "
                        "any other changes to the sale order."
                    )
                )

    @api.onchange("company_id")
    def _onchange_company_id_warning(self):
        self.show_update_pricelist = True
        if self.env.context.get("sale_onchange_first_call"):
            return

        if self.line_ids and self.state == "draft":
            return {
                "warning": {
                    "title": _("Warning for the change of your quotation's company"),
                    "message": _(
                        "Changing the company of an existing quotation might need some "
                        "manual adjustments in the details of the lines. You might "
                        "consider updating the prices."
                    ),
                }
            }

    @api.onchange("partner_id")
    def _onchange_partner_id_warning(self):
        if not self.partner_id:
            return

        partner = self.partner_id
        # If partner has no warning, check its company
        if partner.sale_warn == "no-message" and partner.parent_id:
            partner = partner.parent_id

        if partner.sale_warn and partner.sale_warn != "no-message":
            # Block if partner only has warning but parent company is blocked
            if (
                partner.sale_warn != "block"
                and partner.parent_id
                and partner.parent_id.sale_warn == "block"
            ):
                partner = partner.parent_id

            if partner.sale_warn == "block":
                self.partner_id = False

            return {
                "warning": {
                    "title": _(f"Warning for {partner.name}"),
                    "message": partner.sale_warn_msg,
                }
            }

    @api.onchange("date_commitment", "date_planned")
    def _onchange_date_commitment(self):
        """Warn if the commitment dates is sooner than the expected date"""
        if (
            self.date_commitment
            and self.date_planned
            and self.date_commitment < self.date_planned
        ):
            return {
                "warning": {
                    "title": _("Requested date is too soon."),
                    "message": _(
                        "The delivery date is sooner than the expected date."
                        " You may be unable to honor the delivery date."
                    ),
                }
            }

    @api.onchange("fiscal_position_id")
    def _onchange_fpos_id_show_update_fpos(self):
        if self.line_ids and (
            not self.fiscal_position_id
            or (
                self.fiscal_position_id
                and self._origin.fiscal_position_id != self.fiscal_position_id
            )
        ):
            self.show_update_fpos = True

    @api.onchange("pricelist_id")
    def _onchange_pricelist_id_show_update_prices(self):
        self.show_update_pricelist = bool(self.line_ids)

    @api.onchange("prepayment_percent")
    def _onchange_prepayment_percent(self):
        if not self.prepayment_percent:
            self.require_payment = False

    @api.onchange("line_ids")
    def _onchange_line_ids(self):
        for index, line in enumerate(self.line_ids):
            if line.product_type == "combo" and line.selected_combo_items:
                linked_lines = line._get_lines_linked()
                selected_combo_items = json.loads(line.selected_combo_items)
                if selected_combo_items and len(selected_combo_items) != len(
                    line.product_template_id.combo_ids
                ):
                    raise ValidationError(
                        _(
                            "The number of selected combo items must match the number of available"
                            " combo choices."
                        )
                    )

                # Delete any existing combo item lines.
                delete_commands = [
                    Command.delete(linked_line.id) for linked_line in linked_lines
                ]
                # Create a new combo item line for each selected combo item.
                create_commands = [
                    Command.create(
                        {
                            "product_id": combo_item["product_id"],
                            "product_uom_qty": line.product_uom_qty,
                            "combo_item_id": combo_item["combo_item_id"],
                            "product_no_variant_attribute_value_ids": [
                                Command.set(
                                    combo_item["no_variant_attribute_value_ids"]
                                )
                            ],
                            "product_custom_attribute_value_ids": [Command.clear()]
                            + [
                                Command.create(attribute_value)
                                for attribute_value in combo_item[
                                    "product_custom_attribute_values"
                                ]
                            ],
                            # Combo item lines should come directly after their combo product line.
                            "sequence": line.sequence + item_index + 1,
                            # If the linked line exists in DB, populate linked_line_id, otherwise populate
                            # linked_virtual_id.
                            "linked_line_id": line.id if line._origin else False,
                            "linked_virtual_id": (
                                line.virtual_id if not line._origin else False
                            ),
                        }
                    )
                    for item_index, combo_item in enumerate(selected_combo_items)
                ]
                # Shift any lines coming after the combo product line so that the combo item lines
                # come first.
                update_commands = [
                    Command.update(
                        order_line.id,
                        {
                            "sequence": line.sequence
                            + len(selected_combo_items)
                            + line_index
                            - index
                        },
                    )
                    for line_index, order_line in enumerate(self.line_ids)
                    if line_index > index
                ]

                # Clear `selected_combo_items` to avoid applying the same changes multiple times.
                line.selected_combo_items = False
                self.line_ids = delete_commands + create_commands + update_commands

    # ------------------------------------------------------------
    # SEARCH METHODS
    # ------------------------------------------------------------

    def _search_invoice_ids(self, operator, value):
        if operator == "in" and value:
            self.env.cr.execute(
                """
                SELECT
                    array_agg(so.id)
                FROM
                    sale_order so
                    JOIN sale_order_line sol ON sol.order_id = so.id
                    JOIN account_move_line_sale_order_line_rel soli_rel ON soli_rel.order_line_id = sol.id
                    JOIN account_move_line aml ON aml.id = soli_rel.invoice_line_id
                    JOIN account_move am ON am.id = aml.move_id
                WHERE
                    am.move_type in ('out_invoice', 'out_refund')
                    AND am.id = ANY(%s)
                 """,
                (list(value),),
            )
            so_ids = self.env.cr.fetchone()[0] or []
            return [("id", "in", so_ids)]

        elif operator == "=" and not value:
            # special case for [('invoice_ids', '=', False)], i.e. "Invoices is not set"
            #
            # We cannot just search [('line_ids.invoice_line_ids', '=', False)]
            # because it returns orders with uninvoiced lines, which is not
            # same "Invoices is not set" (some lines may have invoices and some
            # doesn't)
            #
            # A solution is making inverted search first ("orders with invoiced
            # lines") and then invert results ("get all other orders")
            #
            # Domain below returns subset of ('line_ids.invoice_line_ids', '!=', False)
            order_ids = self._search(
                [
                    (
                        "line_ids.invoice_line_ids.move_id.move_type",
                        "in",
                        ("out_invoice", "out_refund"),
                    )
                ]
            )
            return [("id", "not in", order_ids)]

        return [
            (
                "line_ids.invoice_line_ids.move_id.move_type",
                "in",
                ("out_invoice", "out_refund"),
            ),
            ("line_ids.invoice_line_ids.move_id", operator, value),
        ]

    # ------------------------------------------------------------
    # ACTION METHODS
    # ------------------------------------------------------------

    def action_send_quotation(self):
        """Opens a wizard to compose an email, with relevant mail template loaded by default"""
        lang = self.env.context.get("lang")
        ctx = {
            "default_model": "sale.order",
            "default_res_ids": self.ids,
            "default_composition_mode": "comment",
            "default_email_layout_xmlid": "mail.mail_notification_layout_with_responsible_signature",
            "email_notification_allow_footer": True,
            "hide_mail_template_management_options": True,
            "proforma": self.env.context.get("proforma", False),
        }

        if len(self) > 1:
            ctx["default_composition_mode"] = "mass_mail"
        else:
            ctx.update(
                {
                    "force_email": True,
                    "model_description": self.with_context(lang=lang).type_name,
                }
            )
            if not self.env.context.get("hide_default_template"):
                mail_template = self._get_mail_template()
                if mail_template:
                    ctx.update(
                        {
                            "default_template_id": mail_template.id,
                            "mark_so_as_sent": True,
                        }
                    )
                if mail_template and mail_template.lang:
                    lang = mail_template._render_lang(self.ids)[self.id]
            else:
                for order in self:
                    order._portal_ensure_token()

        action = {
            "name": _("Send by Email"),
            "type": "ir.actions.act_window",
            "res_model": "mail.compose.message",
            "view_mode": "form",
            "views": [(False, "form")],
            "view_id": False,
            "target": "new",
            "context": ctx,
        }
        if (
            self.env.context.get("check_document_layout")
            and not self.env.context.get("discard_logo_check")
            and self.env.is_admin()
            and not self.env.company.external_report_layout_id
        ):
            layout_action = self.env[
                "ir.actions.report"
            ]._action_configure_external_report_layout(
                action,
            )
            # Need to remove this context for windows action
            action.pop("close_on_report_download", None)
            layout_action["context"]["dialog_size"] = "extra-large"
            return layout_action

        return action

    def action_view_approval_request(self):
        """Open the approval request associated with this purchase order."""
        self.ensure_one()
        return {
            "name": _("Approval Request"),
            "type": "ir.actions.act_window",
            "res_model": "approval.request",
            "res_id": self.approval_request_id.id,
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "current",
        }

    @api.readonly
    def action_view_discount_wizard(self):
        self.ensure_one()
        return {
            "name": _("Discount"),
            "type": "ir.actions.act_window",
            "res_model": "sale.order.discount",
            "view_mode": "form",
            "target": "new",
        }

    @api.readonly
    def action_preview_sale_order(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "target": "self",
            "url": self.get_portal_url(),
        }

    @api.readonly
    def action_view_invoice(self, invoices=False):
        if not invoices:
            self.invalidate_model(["invoice_ids"])
            invoices = self.mapped("invoice_ids")

        action = self.env["ir.actions.actions"]._for_xml_id(
            "account.action_move_out_invoice_type"
        )
        if len(invoices) > 1:
            action["domain"] = [("id", "in", invoices.ids)]
        elif len(invoices) == 1:
            res = self.env.ref("account.view_move_form", False)
            form_view = [(res and res.id or False, "form")]
            if "views" in action:
                action["views"] = form_view + [
                    (state, view) for state, view in action["views"] if view != "form"
                ]
            else:
                action["views"] = form_view
            action["res_id"] = invoices.id
        else:
            action = {"type": "ir.actions.act_window_close"}

        context = {
            "default_move_type": "out_invoice",
        }
        if len(self) == 1:
            context.update(
                {
                    "default_partner_id": self.partner_id.id,
                    "default_partner_shipping_id": self.partner_shipping_id.id,
                    "default_invoice_payment_term_id": self.payment_term_id.id
                    or self.partner_id.property_payment_term_id.id
                    or self.env["account.move"]
                    .default_get(["invoice_payment_term_id"])
                    .get("invoice_payment_term_id"),
                    "default_invoice_origin": self.name,
                }
            )
        action["context"] = context
        return action

    def action_cancel(self):
        self._can_cancel_except_locked()
        self._can_cancel_except_invoiced()
        inv = self.invoice_ids.filtered(lambda inv: inv.state == "draft")
        inv.button_cancel()
        self.write({"state": "cancel"})
        return True

    def action_confirm(self):
        """Confirm the given quotation(s) and set their confirmation date.

        If the corresponding setting is enabled, also locks the Sale Order.

        :return: True
        :rtype: bool
        :raise: UserError if trying to confirm cancelled SO's"""
        self._can_confirm_proper_state()
        self._can_confirm_has_lines()
        self._can_confirm_lines_have_product()
        for order in self:
            if order._approval_allowed():
                order.write(order._prepare_action_confirm_write_vals())
                order.line_ids._validate_analytic_distribution()

                # Context key 'default_name' is sometimes propagated up to here.
                # We don't need it and it creates issues in the creation of linked records.
                context = order._context.copy()
                context.pop("default_name", None)
                context.pop("default_user_id", None)

                order.with_context(context)._hook_action_confirm()

                user = self[:1].create_uid
                if user and user.sudo().has_group("sale.group_order_auto_lock"):
                    # Public user can confirm SO, so we check the group on any record creator.
                    order.action_lock()

                if self.env.context.get("send_email"):
                    order._mail_confirmation()
            else:
                if not order.approval_request_id:
                    order.approval_request_id = self.env["approval.request"].create(
                        order._prepare_approval_request_vals()
                    )
                    order.approval_request_id.action_confirm()
                else:
                    raise UserError(
                        _(
                            "This order requires approval before it can be confirmed. "
                            "Please wait for the approval to be granted."
                        )
                    )

            if order.partner_id not in order.message_partner_ids:
                order.message_subscribe([order.partner_id.id])

        return True

    def action_draft(self):
        self._can_draft_proper_state()
        orders = self.filtered(lambda order: order.state == "cancel")
        return orders.write(
            {
                "state": "draft",
                "signature": False,
                "signed_by": False,
                "signed_on": False,
            }
        )

    def action_lock(self):
        self.locked = True

    def action_unlock(self):
        self.locked = False

    def action_update_prices(self):
        self.ensure_one()
        self._recompute_prices()
        if self.pricelist_id:
            message = _(
                "Product prices have been recomputed according to pricelist %s.",
                self.pricelist_id._get_html_link(),
            )
        else:
            message = _("Product prices have been recomputed.")
        self.message_post(body=message)

    def action_update_taxes(self):
        self.ensure_one()
        self._recompute_tax_ids()
        if self.partner_id:
            self.message_post(
                body=_(
                    "Product taxes have been recomputed according to fiscal position %s.",
                    (
                        self.fiscal_position_id._get_html_link()
                        if self.fiscal_position_id
                        else ""
                    ),
                )
            )

    # ------------------------------------------------------------
    # MAIL METHODS
    # ------------------------------------------------------------

    def message_post(self, **kwargs):
        if self.env.context.get("mark_so_as_sent"):
            self.filtered(lambda o: o.state == "draft").with_context(
                tracking_disable=True
            ).write({"sent": True})
            kwargs["notify_author_mention"] = kwargs.get("notify_author_mention", True)
        return super().message_post(**kwargs)

    def _notify_get_recipients_groups(self, message, model_description, msg_vals=False):
        # Give access button to users and portal customer as portal is integrated
        # in sale. Customer and portal group have probably no right to see
        # the document so they don't have the access button.
        groups = super()._notify_get_recipients_groups(
            message, model_description, msg_vals=msg_vals
        )
        if not self:
            return groups

        self.ensure_one()
        if self._context.get("proforma"):
            for group in [
                g
                for g in groups
                if g[0] in ("portal_customer", "portal", "follower", "customer")
            ]:
                group[2]["has_button_access"] = False
            return groups

        local_msg_vals = dict(msg_vals or {})

        # portal customers have full access (existence not granted, depending on partner_id)
        try:
            customer_portal_group = next(
                group for group in groups if group[0] == "portal_customer"
            )
        except StopIteration:
            pass

        else:
            access_opt = customer_portal_group[2].setdefault("button_access", {})
            is_tx_pending = self.get_portal_last_transaction().state == "pending"
            if self._has_to_be_signed():
                if self._has_to_be_paid():
                    access_opt["title"] = (
                        _("View Quotation")
                        if is_tx_pending
                        else _("Sign & Pay Quotation")
                    )
                else:
                    access_opt["title"] = _("Accept & Sign Quotation")
            elif self._has_to_be_paid() and not is_tx_pending:
                access_opt["title"] = _("Accept & Pay Quotation")
            elif self.state == "draft":
                access_opt["title"] = _("View Quotation")

        return groups

    def _notify_by_email_prepare_rendering_context(
        self,
        message,
        msg_vals=False,
        model_description=False,
        force_email_company=False,
        force_email_lang=False,
    ):
        render_context = super()._notify_by_email_prepare_rendering_context(
            message,
            msg_vals,
            model_description=model_description,
            force_email_company=force_email_company,
            force_email_lang=force_email_lang,
        )
        lang_code = render_context.get("lang")
        subtitles = [
            render_context["record"].name,
        ]

        if self.amount_total:
            # Do not show the price in subtitles if zero (e.g. e-commerce orders are created empty)
            subtitles.append(
                format_amount(
                    self.env, self.amount_total, self.currency_id, lang_code=lang_code
                ),
            )

        if self.date_validity and self.state == "draft":
            formatted_date = format_date(
                self.env, self.date_validity, lang_code=lang_code
            )
            subtitles.append(_("Expires on %(date)s", date=formatted_date))

        render_context["subtitles"] = subtitles
        return render_context

    def _track_subtype(self, init_values):
        self.ensure_one()
        if "state" in init_values and self.state == "sale":
            return self.env.ref("sale.mt_order_confirmed")
        elif "sent" in init_values and self.sent:
            return self.env.ref("sale.mt_order_sent")
        return super()._track_subtype(init_values)

    def _track_finalize(self):
        """Override of `mail` to prevent logging changes when the SO is in a draft state."""
        if (
            len(self) == 1
            # The method _track_finalize is sometimes called too early or too late and it
            # might cause a desynchronization with the cache, thus this condition is needed.
            and self.env.cache.contains(self, self._fields["state"])
            and self.state == "draft"
        ):
            self.env.cr.precommit.data.pop(f"mail.tracking.{self._name}", {})
            self.env.flush_all()
            return

        return super()._track_finalize()

    def _create_upsell_activity(self):
        if not self:
            return

        self.activity_unlink(["sale.mail_act_sale_upsell"])
        for order in self:
            order_ref = order._get_html_link()
            customer_ref = order.partner_id._get_html_link()
            order.activity_schedule(
                "sale.mail_act_sale_upsell",
                user_id=order.user_id.id or order.partner_id.user_id.id,
                note=_(
                    "Upsell %(order)s for customer %(customer)s",
                    order=order_ref,
                    customer=customer_ref,
                ),
            )

    # ------------------------------------------------------------
    # INVOICING METHODS
    # ------------------------------------------------------------

    def _create_invoices(self, grouped=False, final=False, date=None):
        """Create invoice(s) for the given Sales Order(s).

        :param bool grouped: if True, invoices are grouped by SO id.
            If False, invoices are grouped by keys returned by :meth:`_get_invoice_grouping_keys`
        :param bool final: if True, refunds will be generated if necessary
        :param date: unused parameter
        :returns: created invoices
        :rtype: `account.move` recordset
        :raises: UserError if one of the orders has no invoiceable lines."""
        if not self.env["account.move"].has_access("create"):
            try:
                self.check_access("write")
            except AccessError:
                return self.env["account.move"]

        # 1) Create invoices.
        invoice_vals_list = []
        # Incremental sequencing to keep the lines order on the invoice.
        invoice_item_sequence = 0
        for order in self:
            if order.partner_invoice_id.lang:
                order = order.with_context(lang=order.partner_invoice_id.lang)
            order = order.with_company(order.company_id)
            invoice_vals = order._prepare_invoice_vals()
            invoiceable_lines = order._get_order_lines_invoiceable(final)

            if not any(not line.display_type for line in invoiceable_lines):
                continue

            invoice_line_vals = []
            down_payment_section_added = False
            for line in invoiceable_lines:
                if not down_payment_section_added and line.is_downpayment:
                    # Create a dedicated section for the down payments
                    # (put at the end of the invoiceable_lines)
                    invoice_line_vals.append(
                        Command.create(
                            order._prepare_down_payment_section_line(
                                sequence=invoice_item_sequence
                            )
                        ),
                    )
                    down_payment_section_added = True
                    invoice_item_sequence += 1
                invoice_line_vals.append(
                    Command.create(
                        line._prepare_aml_vals(sequence=invoice_item_sequence)
                    ),
                )
                invoice_item_sequence += 1

            invoice_vals["invoice_line_ids"] += invoice_line_vals
            invoice_vals_list.append(invoice_vals)

        if not invoice_vals_list and self._context.get(
            "raise_if_nothing_to_invoice", True
        ):
            raise UserError(self._nothing_to_invoice_error_message())

        # 2) Manage 'grouped' parameter: group by (partner_id, partner_shipping_id, currency_id).
        if not grouped:
            new_invoice_vals_list = []
            invoice_grouping_keys = self._get_invoice_grouping_keys()
            invoice_vals_list = sorted(
                invoice_vals_list,
                key=lambda x: [
                    x.get(grouping_key) for grouping_key in invoice_grouping_keys
                ],
            )
            for _grouping_keys, invoices in groupby(
                invoice_vals_list,
                key=lambda x: [
                    x.get(grouping_key) for grouping_key in invoice_grouping_keys
                ],
            ):
                origins = set()
                payment_refs = set()
                refs = set()
                ref_invoice_vals = None
                for invoice_vals in invoices:
                    if not ref_invoice_vals:
                        ref_invoice_vals = invoice_vals
                    else:
                        ref_invoice_vals["invoice_line_ids"] += invoice_vals[
                            "invoice_line_ids"
                        ]
                    origins.add(invoice_vals["invoice_origin"])
                    payment_refs.add(invoice_vals["payment_reference"])
                    refs.add(invoice_vals["ref"])
                ref_invoice_vals.update(
                    {
                        "ref": ", ".join(refs)[:2000],
                        "invoice_origin": ", ".join(origins),
                        "payment_reference": len(payment_refs) == 1
                        and payment_refs.pop()
                        or False,
                    }
                )
                new_invoice_vals_list.append(ref_invoice_vals)
            invoice_vals_list = new_invoice_vals_list

        # 3) Create invoices.

        # As part of the invoice creation, we make sure the sequence of multiple SO do not interfere
        # in a single invoice. Example:
        # SO 1:
        # - Section A (sequence: 10)
        # - Product A (sequence: 11)
        # SO 2:
        # - Section B (sequence: 10)
        # - Product B (sequence: 11)
        #
        # If SO 1 & 2 are grouped in the same invoice, the result will be:
        # - Section A (sequence: 10)
        # - Section B (sequence: 10)
        # - Product A (sequence: 11)
        # - Product B (sequence: 11)
        #
        # Resequencing should be safe, however we resequence only if there are less invoices than
        # orders, meaning a grouping might have been done. This could also mean that only a part
        # of the selected SO are invoiceable, but resequencing in this case shouldn't be an issue.
        if len(invoice_vals_list) < len(self):
            SaleOrderLine = self.env["sale.order.line"]
            for invoice in invoice_vals_list:
                sequence = 1
                for line in invoice["invoice_line_ids"]:
                    line[2]["sequence"] = SaleOrderLine._get_invoice_line_sequence(
                        new=sequence, old=line[2]["sequence"]
                    )
                    sequence += 1

        moves = self._hook_create_invoices(invoice_vals_list, final)

        # 4) Some moves might actually be refunds: convert them if the total amount is negative
        # We do this after the moves have been created since we need taxes, etc. to know if the total
        # is actually negative or not
        if final and (
            moves_to_switch := moves.sudo().filtered(lambda m: m.amount_total < 0)
        ):
            with self.env.protecting([moves._fields["team_id"]], moves_to_switch):
                moves_to_switch.action_switch_move_type()
                self.invoice_ids._set_reversed_entry(moves_to_switch)

        for move in moves:
            if final:
                # Downpayment might have been determined by a fixed amount set by the user.
                # This amount is tax included. This can lead to rounding issues.
                # E.g. a user wants a 100€ DP on a product with 21% tax.
                # 100 / 1.21 = 82.64, 82.64 * 1,21 = 99.99
                # This is already corrected by adding/removing the missing cents on the DP invoice,
                # but must also be accounted for on the final invoice.
                delta_amount = 0
                for order_line in self.line_ids:
                    if not order_line.is_downpayment:
                        continue

                    inv_amt = order_amt = 0
                    for invoice_line in order_line.invoice_line_ids:
                        sign = 1 if invoice_line.move_id.is_inbound() else -1
                        if invoice_line.move_id == move:
                            inv_amt += invoice_line.price_total * sign
                        elif (
                            invoice_line.move_id.state != "cancel"
                        ):  # filter out canceled dp lines
                            order_amt += invoice_line.price_total * sign
                    if inv_amt and order_amt:
                        # if not inv_amt, this order line is not related to current move
                        # if no order_amt, dp order line was not invoiced
                        delta_amount += inv_amt + order_amt

                if not move.currency_id.is_zero(delta_amount):
                    receivable_line = move.line_ids.filtered(
                        lambda aml: aml.account_id.account_type == "asset_receivable"
                    )[:1]
                    product_lines = move.line_ids.filtered(
                        lambda aml: aml.display_type == "product" and aml.is_downpayment
                    )
                    tax_lines = move.line_ids.filtered(
                        lambda aml: aml.tax_line_id.amount_type not in (False, "fixed")
                    )
                    if tax_lines and product_lines and receivable_line:
                        line_commands = [
                            Command.update(
                                receivable_line.id,
                                {
                                    "amount_currency": receivable_line.amount_currency
                                    + delta_amount,
                                },
                            )
                        ]
                        delta_sign = 1 if delta_amount > 0 else -1
                        for lines, attr, sign in (
                            (
                                product_lines,
                                "price_total",
                                -1 if move.is_inbound() else 1,
                            ),
                            (tax_lines, "amount_currency", 1),
                        ):
                            remaining = delta_amount
                            lines_len = len(lines)
                            for line in lines:
                                if (
                                    move.currency_id.compare_amounts(remaining, 0)
                                    != delta_sign
                                ):
                                    break

                                amt = delta_sign * max(
                                    move.currency_id.rounding,
                                    abs(move.currency_id.round(remaining / lines_len)),
                                )
                                remaining -= amt
                                line_commands.append(
                                    Command.update(
                                        line.id, {attr: line[attr] + amt * sign}
                                    )
                                )
                        move.line_ids = line_commands

            move.message_post_with_source(
                "mail.message_origin_link",
                render_values={
                    "self": move,
                    "origin": move.line_ids.sale_line_ids.order_id,
                },
                subtype_xmlid="mail.mt_note",
            )
        return moves

    def _hook_create_invoices(self, invoice_vals_list, final):
        """Small method to allow overriding the behavior right
        at the point of an invoice is created."""
        # Manage the creation of invoices in sudo because a salesperson must be able
        # to generate an invoice from a sale order without "billing" access rights.
        # However, he should not be able to create an invoice from scratch.
        return (
            self.env["account.move"]
            .sudo()
            .with_context(default_move_type="out_invoice")
            .create(invoice_vals_list)
        )

    def _get_invoice_grouping_keys(self):
        return ["company_id", "partner_id", "partner_shipping_id", "currency_id"]

    def _get_order_lines_invoiceable(self, final=False):
        """Return the invoiceable lines for order `self`."""
        down_payment_line_ids = []
        invoiceable_line_ids = []
        pending_section = None
        precision = self.env["decimal.precision"].precision_get("Product Unit")
        for line in self.line_ids:
            # Only invoice the section if one of its lines is invoiceable
            if line.display_type == "line_section":
                pending_section = line
                continue

            if line.display_type != "line_note" and float_is_zero(
                line.qty_to_invoice, precision_digits=precision
            ):
                continue

            if (
                line.qty_to_invoice > 0
                or (line.qty_to_invoice < 0 and final)
                or line.display_type == "line_note"
            ):
                if line.is_downpayment:
                    # Keep down payment lines separately, to put them together
                    # at the end of the invoice, in a specific dedicated section.
                    down_payment_line_ids.append(line.id)
                    continue

                if pending_section:
                    invoiceable_line_ids.append(pending_section.id)
                    pending_section = None

                invoiceable_line_ids.append(line.id)

        return self.env["sale.order.line"].browse(
            invoiceable_line_ids + down_payment_line_ids
        )

    def _get_order_lines_price_updatable(self):
        """Hook to exclude specific lines which should not be updated based on price list recomputation"""
        return self.line_ids.filtered(lambda line: not line.display_type)

    def _nothing_to_invoice_error_message(self):
        return _(
            "Cannot create an invoice. No items are available to invoice.\n\n"
            "To resolve this issue, please ensure that:\n"
            "   \u2022 The products have been delivered before attempting to invoice them.\n"
            "   \u2022 The invoicing policy of the product is configured correctly.\n\n"
            "If you want to invoice based on ordered quantities instead:\n"
            "   \u2022 For consumable or storable products, open the product, go to the 'General Information' tab and change the 'Invoicing Policy' from 'Delivered Quantities' to 'Ordered Quantities'.\n"
            "   \u2022 For services (and other products), change the 'Invoicing Policy' to 'Prepaid/Fixed Price'.\n"
        )

    def _prepare_invoice_vals(self):
        """Prepare the dict of values to create the new invoice for a sales order. This method may be
        overridden to implement custom invoice generation (making sure to call super() to establish
        a clean extension chain)."""
        self.ensure_one()
        txs_to_be_linked = self.transaction_ids.sudo().filtered(
            lambda tx: (
                tx.state in ("pending", "authorized")
                or tx.state == "done"
                and not (tx.payment_id and tx.payment_id.is_reconciled)
            )
        )
        values = {
            "move_type": "out_invoice",
            "company_id": self.company_id.id,
            "currency_id": self.currency_id.id,
            "partner_id": self.partner_invoice_id.id,
            "team_id": self.team_id.id,
            "partner_shipping_id": self.partner_shipping_id.id,
            "fiscal_position_id": (
                self.fiscal_position_id
                or self.fiscal_position_id._get_fiscal_position(self.partner_invoice_id)
            ).id,
            "invoice_payment_term_id": self.payment_term_id.id,
            "invoice_user_id": self.user_id.id,
            "campaign_id": self.campaign_id.id,
            "medium_id": self.medium_id.id,
            "source_id": self.source_id.id,
            "invoice_origin": self.name,
            "ref": self.client_order_ref or "",
            "narration": self.notes,
            "payment_reference": self.reference,
            "transaction_ids": [Command.set(txs_to_be_linked.ids)],
            "invoice_line_ids": [],
        }
        if self.journal_id:
            values["journal_id"] = self.journal_id.id
        return values

    # ------------------------------------------------------------
    # PAYMENT METHODS
    # ------------------------------------------------------------

    def _force_lines_to_invoice_policy_order(self):
        """Force the qty_to_invoice to be computed as if the invoice_policy
        was set to "Ordered quantities", independently of the product configuration.

        This is needed for the automatic invoice logic, as we want to automatically
        invoice the full SO when it's paid."""
        for line in self.line_ids:
            if line.state == "sale":
                # No need to set 0 as it is already the standard logic in the compute method.
                line.qty_to_invoice = line.product_uom_qty - line.qty_invoiced

    def payment_action_capture(self):
        """Capture all transactions linked to this sale order."""
        self.ensure_one()
        payment_utils.check_rights_on_recordset(self)
        # In sudo mode to bypass the checks on the rights on the transactions.
        return self.transaction_ids.sudo().action_capture()

    def payment_action_void(self):
        """Void all transactions linked to this sale order."""
        payment_utils.check_rights_on_recordset(self)
        # In sudo mode to bypass the checks on the rights on the transactions.
        self.authorized_transaction_ids.sudo().action_void()

    def _get_default_payment_link_values(self):
        self.ensure_one()
        amount_max = self.amount_total - self.amount_paid
        # Always default to the minimum value needed to confirm the order:
        # - order is not confirmed yet
        # - can be confirmed online
        # - we have still not paid enough for confirmation.
        prepayment_amount = self._get_prepayment_required_amount()
        if (
            self.state == "draft"
            and self.require_payment
            and self.currency_id.compare_amounts(prepayment_amount, self.amount_paid)
            > 0
        ):
            amount = prepayment_amount - self.amount_paid
        else:
            amount = amount_max

        return {
            "currency_id": self.currency_id.id,
            "partner_id": self.partner_invoice_id.id,
            "amount": amount,
            "amount_max": amount_max,
            "amount_paid": self.amount_paid,
        }

    @api.model
    def _get_note_url(self):
        return self.env.company.get_base_url()

    def _get_order_lines_to_report(self):
        down_payment_lines = self.line_ids.filtered(
            lambda line: line.is_downpayment
            and not line.display_type
            and not line._get_downpayment_state()
        )

        def show_line(line):
            if not line.is_downpayment:
                return True

            elif line.display_type and down_payment_lines:
                return True  # Only show the down payment section if down payments were posted

            elif line in down_payment_lines:
                return True  # Only show posted down payments

            else:
                return False

        return self.line_ids.filtered(show_line)

    def get_portal_last_transaction(self):
        self.ensure_one()
        return self.transaction_ids.sudo()._get_last()

    # ------------------------------------------------------------
    # PORTAL METHODS
    # ------------------------------------------------------------

    def _has_to_be_signed(self):
        """A sale order has to be signed when:
        - its state is 'draft' or `sent`
        - it's not expired;
        - it requires a signature;
        - it's not already signed.

        Note: self.ensure_one()

        :return: Whether the sale order has to be signed.
        :rtype: bool"""
        self.ensure_one()
        return (
            self.state == "draft"
            and not self.is_expired
            and self.require_signature
            and not self.signature
        )

    def _has_to_be_paid(self):
        """A sale order has to be paid when:
        - its state is 'draft' or `sent`;
        - it's not expired;
        - it requires a payment;
        - the last transaction's state isn't `done`;
        - the total amount is strictly positive.
        - confirmation amount is not reached

        Note: self.ensure_one()

        :return: Whether the sale order has to be paid.
        :rtype: bool"""
        self.ensure_one()
        return (
            self.state == "draft"
            and not self.is_expired
            and self.require_payment
            and self.amount_total > 0
            and not self._is_confirmation_amount_reached()
        )

    def _get_name_portal_content_view(self):
        """This method can be inherited by localizations who want to localize the online quotation view."""
        self.ensure_one()
        return "sale.sale_order_portal_content"

    def _get_name_tax_totals_view(self):
        """This method can be inherited by localizations who want to localize
        the taxes displayed on the portal and sale order report."""
        return "sale.document_tax_totals"

    def _get_portal_return_action(self):
        """Return the action used to display orders when returning from customer portal."""
        self.ensure_one()
        return self.env.ref("sale.action_quotations_with_onboarding")

    def _get_report_base_filename(self):
        self.ensure_one()
        return f"{self.type_name} {self.name}"

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    def _add_base_lines_for_early_payment_discount(self):
        """When applying a payment term with an early payment discount,
        and when said payment term computes the tax on the "mixed" setting,
        the tax computation is always based on the discounted amount untaxed.
        Creates the necessary line for this behavior to be displayed.
        :returns: array containing the necessary lines or empty array
        if the payment term isn't epd mixed"""
        self.ensure_one()
        epd_lines = []
        if (
            self.payment_term_id.early_discount
            and self.payment_term_id.early_pay_discount_computation == "mixed"
            and self.payment_term_id.discount_percentage
        ):
            percentage = self.payment_term_id.discount_percentage
            currency = self.currency_id or self.company_id.currency_id
            for line in self.line_ids.filtered(lambda x: not x.display_type):
                line_amount_after_discount = (line.price_subtotal / 100) * percentage
                epd_lines.append(
                    self.env["account.tax"]._prepare_base_line_for_taxes_computation(
                        record=self,
                        price_unit=-line_amount_after_discount,
                        quantity=1.0,
                        currency_id=currency,
                        sign=1,
                        special_type="early_payment",
                        tax_ids=line.tax_ids,
                    )
                )
                epd_lines.append(
                    self.env["account.tax"]._prepare_base_line_for_taxes_computation(
                        record=self,
                        price_unit=line_amount_after_discount,
                        quantity=1.0,
                        currency_id=currency,
                        sign=1,
                        special_type="early_payment",
                    )
                )
        return epd_lines

    def _create_downpayments(self):
        """Generate invoices as down payments for sale order.

        :return: The generated down payment invoices.
        :rtype: recordset of `account.move`"""
        generated_invoices = self.env["account.move"]
        for order in self:
            wizard = order.env["sale.advance.payment.inv"].create(
                {
                    "sale_order_ids": order,
                    "advance_payment_method": "fixed",
                    "fixed_amount": order.amount_paid,
                }
            )
            generated_invoices |= wizard._create_invoices(order)
        return generated_invoices

    def _filter_product_documents(self, documents):
        return documents.filtered(
            lambda document: document.attached_on_sale == "quotation"
            or (self.state == "sale" and document.attached_on_sale == "sale_order")
        )

    def _hook_action_cancel(self):
        pass

    def _hook_action_confirm(self):
        """Implementation of additional mechanism of Sales Order confirmation.
        This method should be extended when the confirmation should generated
        other documents. In this method, the SO are in 'sale' state (not yet 'done')."""
        pass

    def _phone_get_number_fields(self):
        """No phone or mobile field is available on sale model. Instead SMS will
        fallback on partner-based computation using ``_mail_get_partner_fields``."""
        return []

    def _recompute_tax_ids(self):
        lines_to_recompute = self._get_order_lines_price_updatable()
        lines_to_recompute._compute_tax_ids()
        self.show_update_fpos = False

    def _recompute_prices(self):
        lines_to_recompute = self._get_order_lines_price_updatable()
        lines_to_recompute.invalidate_recordset(["pricelist_item_id"])
        lines_to_recompute.with_context(
            force_price_recomputation=True
        )._compute_price_unit()
        # Special case: we want to overwrite the existing discount on _recompute_prices call
        # i.e. to make sure the discount is correctly reset
        # if pricelist rule is different than when the price was first computed.
        lines_to_recompute.discount = 0.0
        lines_to_recompute._compute_discount()
        self.show_update_pricelist = False

    def _mail_confirmation(self):
        """Send a mail to the SO customer to inform them that their order has been confirmed.

        :return: None"""
        for order in self:
            mail_template = order._get_mail_template_confirmation()
            order._mail_notification(mail_template)

    def _mail_notification(self, mail_template):
        """Send a mail to the customer

        Note: self.ensure_one()

        :param mail.template mail_template: the template used to generate the mail
        :return: None"""
        self.ensure_one()

        if not mail_template:
            return

        if self.env.su:
            # sending mail in sudo was meant for it being sent from superuser
            self = self.with_user(SUPERUSER_ID)

        self.with_context(force_send=True).message_post_with_source(
            mail_template,
            email_layout_xmlid="mail.mail_notification_layout_with_responsible_signature",
            subtype_xmlid="mail.mt_comment",
        )

    def _mail_payment_succeeded(self):
        """Send a mail to the SO customer to inform them that a payment has been initiated.

        :return: None"""
        mail_template = self.env.ref(
            "sale.mail_template_sale_payment_executed", raise_if_not_found=False
        )
        for order in self:
            order._mail_notification(mail_template)

    def get_approval_category(self):
        return self.env.ref("sale.approval_category_sale")

    def _get_date_planned(self, date_planneds):
        self.ensure_one()
        return min(date_planneds)

    def _get_lang(self):
        self.ensure_one()
        if self.partner_id.lang and not self.partner_id.is_public:
            return self.partner_id.lang

        return self.env.lang

    def _get_mail_template(self):
        """Get the appropriate mail template for the current sales order based on its state.

        If the SO is confirmed, we return the mail template for the sale confirmation.
        Otherwise, we return the quotation email template.

        :return: The correct mail template based on the current status
        :rtype: record of `mail.template` or `None` if not found"""
        self.ensure_one()
        if self.env.context.get("proforma"):
            return self.env.ref(
                "sale.email_template_proforma", raise_if_not_found=False
            )

        elif self.state != "sale":
            return self.env.ref(
                "sale.email_template_edi_sale", raise_if_not_found=False
            )

        else:
            return self._get_mail_template_confirmation()

    def _get_mail_template_confirmation(self):
        """Get the mail template sent on SO confirmation (or for confirmed SO's).

        :return: `mail.template` record or None if default template wasn't found"""
        self.ensure_one()
        default_confirmation_template_id = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("sale.default_confirmation_template")
        )
        default_confirmation_template = (
            default_confirmation_template_id
            and self.env["mail.template"]
            .browse(int(default_confirmation_template_id))
            .exists()
        )
        if default_confirmation_template:
            return default_confirmation_template

        else:
            return self.env.ref(
                "sale.mail_template_sale_confirmation", raise_if_not_found=False
            )

    def _get_order_lines_copiable(self):
        """Returns the order lines that can be copied to a new order."""
        return self.line_ids.filtered(lambda l: not l.is_downpayment)

    def _get_prepayment_required_amount(self):
        """Return the minimum amount needed to confirm automatically the quotation.

        Note: self.ensure_one()

        :return: The minimum amount needed to confirm automatically the quotation.
        :rtype: float"""
        self.ensure_one()
        if self.prepayment_percent == 1.0 or not self.require_payment:
            return self.amount_total
        else:
            return self.currency_id.round(self.amount_total * self.prepayment_percent)

    def _get_product_documents(self):
        self.ensure_one()
        documents = (
            self.line_ids.product_id.product_document_ids
            | self.line_ids.product_template_id.product_document_ids
        )
        return self._filter_product_documents(documents).sorted()

    def _prepare_action_confirm_write_vals(self):
        """Prepare the sales order confirmation values.

        Note: self can contain multiple records.

        :return: Sales Order confirmation values
        :rtype: dict"""
        return {"state": "sale", "date_order": fields.Datetime.now()}

    def _prepare_analytic_account_data(self, prefix=None):
        """Prepare SO analytic account creation values.

        :return: `account.analytic.account` creation values
        :rtype: dict"""
        self.ensure_one()
        name = self.name
        if prefix:
            name = prefix + ": " + self.name
        project_plan, _other_plans = self.env["account.analytic.plan"]._get_all_plans()
        return {
            "name": name,
            "code": self.client_order_ref,
            "company_id": self.company_id.id,
            "plan_id": project_plan.id,
            "partner_id": self.partner_id.id,
        }

    def _prepare_approval_request_vals(self):
        self.ensure_one()
        category = self.get_approval_category()
        res = {
            "company_id": self.company_id.id,
            "category_id": category.id,
            "partner_id": self.partner_id.id,
            "date": fields.Datetime.now(),
            "name": self.name,
            "amount": self.amount_total,
            "reason": self.notes,
        }
        return res

    def _prepare_down_payment_section_line(self, **optional_values):
        """Prepare the values to create a new down payment section.

        :param dict optional_values: any parameter that should be added to the returned down payment section
        :return: `account.move.line` creation values
        :rtype: dict"""
        self.ensure_one()
        context = {"lang": self.partner_id.lang}
        down_payments_section_line = {
            "display_type": "line_section",
            "name": _("Down Payments"),
            "product_id": False,
            "product_uom_id": False,
            "quantity": 0,
            "discount": 0,
            "price_unit": 0,
            "account_id": False,
            **optional_values,
        }
        del context
        return down_payments_section_line

    # ------------------------------------------------------------
    # VALIDATIONS
    # ------------------------------------------------------------

    def _approval_allowed(self):
        """Returns whether the order qualifies to be approved by the current user"""
        self.ensure_one()
        return not self.company_id.po_approval or self.approval_state == "approved"

    def _is_confirmation_amount_reached(self):
        """Return whether `self.amount_paid` is higher than the prepayment required amount.

        Note: self.ensure_one()

        :return: Whether `self.amount_paid` is higher than the prepayment required amount.
        :rtype: bool"""
        self.ensure_one()
        amount_comparison = self.currency_id.compare_amounts(
            self._get_prepayment_required_amount(),
            self.amount_paid,
        )
        return amount_comparison <= 0

    def _is_paid(self):
        """Return whether the sale order is paid or not based on the linked transactions.

        A sale order is considered paid if the sum of all the linked transaction is equal to or
        higher than `self.amount_total`.

        :return: Whether the sale order is paid or not.
        :rtype: bool"""
        self.ensure_one()
        return (
            self.currency_id.compare_amounts(self.amount_paid, self.amount_total) >= 0
        )

    def _is_readonly(self):
        """Return Whether the sale order is read-only or not based on the state or the lock status.

        A sale order is considered read-only if its state is 'cancel' or if the sale order is
        locked.

        :return: Whether the sale order is read-only or not.
        :rtype: bool"""
        self.ensure_one()
        return self.state == "cancel" or self.locked

    def _can_confirm_has_lines(self):
        orders_without_lines = self.filtered(lambda order: not order.line_ids)
        if orders_without_lines:
            raise UserError(_("No lines on this order. It can not be confirmed."))

    def _can_confirm_lines_have_product(self):
        orders_without_line_product = self.filtered(
            lambda order: any(
                not line.display_type
                and not line.is_downpayment
                and not line.product_id
                for line in order.line_ids
            )
        )
        if orders_without_line_product:
            raise UserError(
                _(
                    "A line on these orders is missing a product. It can not be confirmed."
                )
            )

    def _can_confirm_proper_state(self):
        orders_wrong_state = self.filtered(lambda order: order.state != "draft")
        if orders_wrong_state:
            raise UserError(_("Some orders are not in a state requiring confirmation."))

    def _can_cancel_except_locked(self):
        if any(order.locked for order in self):
            raise UserError(
                _("You cannot cancel a locked order. Please unlock it first.")
            )

    def _can_cancel_except_invoiced(self):
        """Returns whether the order qualifies to be canceled by the current user"""
        orders_with_invoices = self.filtered(
            lambda o: any(i.state == "posted" for i in o.invoice_ids)
        )
        if orders_with_invoices:
            raise UserError(
                _(
                    "Unable to cancel sale order(s): %s. "
                    "You must first cancel their related invoices.",
                    format_list(self.env, orders_with_invoices.mapped("display_name")),
                )
            )

    def _can_draft_proper_state(self):
        if any(order.state != "cancel" for order in self):
            raise UserError(
                _("You cannot draft an order in a state different from 'Cancelled'.")
            )
