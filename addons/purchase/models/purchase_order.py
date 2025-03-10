from collections import defaultdict
from dateutil.relativedelta import relativedelta
from markupsafe import escape, Markup
from pytz import timezone
from werkzeug.urls import url_encode

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Command
from odoo.osv import expression
from odoo.tools import format_amount, format_date, format_list, formatLang, groupby, SQL
from odoo.tools.float_utils import float_is_zero, float_repr
from odoo.tools.translate import _


class PurchaseOrder(models.Model):
    """Inherit PurchaseOrder"""

    _name = "purchase.order"
    _description = "Purchase Order"
    _inherit = [
        "mail.activity.mixin",
        "mail.thread",
        "portal.mixin",
        "product.catalog.mixin",
    ]
    _check_company_auto = True
    _rec_names_search = ["name", "partner_ref"]
    _order = "priority desc, id desc"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company.id,
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
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Vendor",
        required=True,
        change_default=True,
        check_company=True,
        tracking=True,
        help="You can find a vendor by its Name, TIN, Email or Internal Reference.",
    )
    count_partner_supplier_invoice = fields.Integer(
        related="partner_id.count_supplier_invoice"
    )
    dest_address_id = fields.Many2one(
        comodel_name="res.partner",
        string="Dropship Address",
        check_company=True,
        help="Put an address if you want to deliver directly from the vendor to the customer. "
        "Otherwise, keep empty to deliver to your own company.",
    )
    fiscal_position_id = fields.Many2one(
        comodel_name="account.fiscal.position",
        string="Fiscal Position",
        compute="_compute_fiscal_position_id",
        store=True,
        precompute=True,
        readonly=False,
        check_company=True,
        domain='[("company_id", "in", (False, company_id))]',
        help="Fiscal positions are used to adapt taxes and accounts for particular customers "
        "or sales orders/invoices. The default value comes from the customer.",
    )
    tax_country_id = fields.Many2one(
        comodel_name="res.country",
        compute="_compute_tax_country_id",
        # Avoid access error on fiscal position when reading a
        # purchase order with company != user.company_ids
        compute_sudo=True,
        help="Technical field to filter the available taxes depending on "
        "the fiscal country and fiscal position.",
    )
    incoterm_id = fields.Many2one(
        comodel_name="account.incoterms",
        string="Incoterm",
        help="International Commercial Terms are a series of predefined "
        "commercial terms used in international transactions.",
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
        string="Buyer",
        compute="_compute_user_id",
        store=True,
        precompute=True,
        readonly=False,
        domain=lambda self: """
            [
                ('group_ids', '=', {}),
                ('share', '=', False),
                ('company_ids', '=', company_id),
            ]
        """.format(
            self.env.ref("purchase.group_purchase_user").id
        ),
        tracking=True,
        index=True,
    )
    journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Billing Journal",
        compute="_compute_journal_id",
        store=True,
        precompute=True,
        readonly=False,
        check_company=True,
        domain=[("type", "=", "purchase")],
        help="If set, the PO will invoice in this journal; "
        "otherwise the purchase journal with the lowest sequence is used.",
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
        selection=[
            ("draft", "RFQ"),
            ("purchase", "Purchase Order"),
            ("cancel", "Cancelled"),
        ],
        string="Status",
        default="draft",
        readonly=True,
        copy=False,
        tracking=True,
        index=True,
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
        help="THE RFQ has been sent to the vendor.",
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
    date_order = fields.Datetime(
        string="Order Deadline",
        required=True,
        default=fields.Datetime.now,
        copy=False,
        index=True,
        help="Depicts the date within which the Quotation should be "
        "confirmed and converted into a purchase order.",
    )
    date_validity = fields.Date(
        string="Expiration",
        # compute="_compute_date_validity",
        # store=True,
        # precompute=True,
        readonly=False,
        copy=False,
        help="Validity of the order, after that you will not able to sign & pay the quotation.",
    )
    date_approve = fields.Datetime(
        string="Approval Date",
        readonly=True,
        copy=False,
        index=True,
    )
    date_calendar_start = fields.Datetime(
        compute="_compute_date_calendar_start",
        store=True,
        readonly=True,
    )
    origin = fields.Char(
        string="Source",
        copy=False,
        help="Reference of the document that generated this purchase order "
        "request (e.g. a sales order)",
    )
    partner_ref = fields.Char(
        string="Vendor Reference",
        copy=False,
        help="Reference of the sales order or bid sent by the vendor. "
        "It's used to do the matching when you receive the "
        "products as this reference is usually written on the "
        "delivery order sent by your vendor.",
    )
    notes = fields.Html(string="Terms and Conditions")

    # Order line block
    line_ids = fields.One2many(
        comodel_name="purchase.order.line",
        inverse_name="order_id",
        string="Order Lines",
        copy=True,
        auto_join=True,
    )
    product_id = fields.Many2one(
        related="line_ids.product_id",
        string="Product",
    )
    date_planned = fields.Datetime(
        string="Expected Arrival",
        compute="_compute_date_planned",
        store=True,
        readonly=False,
        copy=False,
        index=True,
        help="Delivery date promised by vendor. "
        "This date is used to determine expected arrival of products.",
    )
    amount_untaxed = fields.Monetary(
        string="Untaxed Amount",
        compute="_compute_amounts",
        store=True,
        readonly=True,
        tracking=True,
    )
    amount_tax = fields.Monetary(
        string="Taxes",
        compute="_compute_amounts",
        store=True,
        readonly=True,
        tracking=True,
    )
    amount_total = fields.Monetary(
        string="Total",
        compute="_compute_amounts",
        store=True,
        readonly=True,
        tracking=True,
    )
    tax_totals = fields.Binary(
        compute="_compute_tax_totals",
        exportable=False,
    )

    # Invoice block
    invoice_ids = fields.Many2many(
        comodel_name="account.move",
        string="Bills",
        compute="_compute_invoice_ids",
        store=True,
        copy=False,
    )
    count_invoice_ids = fields.Integer(
        string="Bill Count",
        default=0,
        compute="_compute_invoice_ids",
        store=True,
        copy=False,
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
        readonly=True,
        copy=False,
    )

    type_name = fields.Char(
        string="Type Name",
        compute="_compute_type_name",
    )
    receipt_reminder_email = fields.Boolean(
        string="Receipt Reminder Email",
        compute="_compute_receipt_reminder_email",
        store=True,
        readonly=False,
    )
    reminder_date_before_receipt = fields.Integer(
        string="Days Before Receipt",
        compute="_compute_receipt_reminder_email",
        store=True,
        readonly=False,
    )
    acknowledged = fields.Boolean(
        string="Acknowledged",
        copy=False,
        tracking=True,
        help="It indicates that the vendor has acknowledged the receipt of the purchase order.",
    )
    is_late = fields.Boolean(
        string="Is Late",
        store=False,
        search="_search_is_late",
    )
    show_comparison = fields.Boolean(
        string="Show Comparison",
        compute="_compute_show_comparison",
    )

    # ------------------------------------------------------------
    # CONSTRAINTS
    # ------------------------------------------------------------

    @api.constrains("company_id", "line_ids")
    def _check_line_ids_company_id(self):
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
                        "Your quotation contains products from company %(product_company)s whereas "
                        "your quotation belongs to company %(quote_company)s.\n"
                        "Please change the company of your quotation or remove the products "
                        "from other companies (%(bad_products)s).",
                        product_company=", ".join(
                            invalid_companies.sudo().mapped("display_name")
                        ),
                        quote_company=order.company_id.display_name,
                        bad_products=", ".join(bad_products.mapped("display_name")),
                    )
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
                    "purchase.order", sequence_date=seq_date
                )
        return super().create(vals_list)

    def copy(self, default=None):
        ctx = dict(self.env.context)
        ctx.pop("default_product_id", None)
        self = self.with_context(ctx)
        new_orders = super().copy(default=default)
        for line in new_orders.line_ids:
            if line.product_id:
                seller = line.product_id._select_seller(
                    partner_id=line.partner_id,
                    quantity=line.product_qty,
                    date=line.order_id.date_order and line.order_id.date_order.date(),
                    uom_id=line.product_uom_id,
                )
                line.date_planned = line._get_date_planned(seller)
        return new_orders

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft_or_cancel(self):
        for order in self:
            if order.state not in ("draft", "cancel"):
                raise UserError(
                    _(
                        "You can not delete a confirmed orders. "
                        "You must first cancel it."
                    )
                )

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    def _compute_access_url(self):
        super()._compute_access_url()
        for order in self:
            order.access_url = f"/my/purchase/{order.id}"

    def _compute_journal_id(self):
        self.journal_id = False

    @api.depends("state")
    def _compute_type_name(self):
        for order in self:
            if order.state in ("draft", "cancel"):
                order.type_name = _("Quotation")
            else:
                order.type_name = _("Purchase Order")

    @api.depends("state", "date_order", "date_approve")
    def _compute_date_calendar_start(self):
        for order in self:
            order.date_calendar_start = (
                order.date_approve if order.state == "purchase" else order.date_order
            )

    @api.depends("approval_request_id")
    def _compute_approval_state(self):
        for order in self:
            if order.approval_request_id:
                order.approval_state = order.approval_request_id.state
            else:
                order.approval_state = "none"

    @api.depends("partner_id")
    def _compute_payment_term_id(self):
        for order in self:
            order = order.with_company(order.company_id)
            order.payment_term_id = order.partner_id.property_supplier_payment_term_id

    @api.depends("partner_id")
    def _compute_user_id(self):
        for order in self:
            if order.partner_id and not (order._origin.id and order.user_id):
                # Recompute the buyer on partner change
                #   * if partner is set (is required anyway, so it will be set sooner or later)
                #   * if the order is not saved or has no buyer already
                order.user_id = (
                    order.partner_id.purchase_user_id
                    or order.partner_id.commercial_partner_id.purchase_user_id
                    or (
                        self.env.user.has_group("purchase.group_purchase_user")
                        and self.env.user
                    )
                )

    @api.depends("company_id", "partner_id")
    def _compute_currency_id(self):
        default_currency = self._context.get("default_currency_id")
        for order in self:
            order = order.with_company(order.company_id)
            order.currency_id = (
                default_currency
                or order.partner_id.property_purchase_currency_id
                or order.company_id.currency_id
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

    @api.depends("company_id", "partner_id")
    def _compute_fiscal_position_id(self):
        """Trigger the change of fiscal position when the shipping address is modified."""
        cache = {}
        for order in self:
            if not order.partner_id:
                order.fiscal_position_id = False
                continue

            # fpos_id_before = order.fiscal_position_id.id
            key = (
                order.company_id.id,
                order.partner_id.id,
                # order.partner_shipping_id.id,
            )
            if key not in cache:
                cache[key] = (
                    self.env["account.fiscal.position"]
                    .with_company(order.company_id)
                    ._get_fiscal_position(order.partner_id)
                    .id
                )
            # if fpos_id_before != cache[key] and order.line_ids:
            #     order.show_update_fpos = True
            order.fiscal_position_id = cache[key]

    @api.depends(
        "company_id.account_fiscal_country_id",
        "fiscal_position_id.country_id",
        "fiscal_position_id.foreign_vat",
    )
    def _compute_tax_country_id(self):
        for order in self:
            if order.fiscal_position_id.foreign_vat:
                order.tax_country_id = order.fiscal_position_id.country_id
            else:
                order.tax_country_id = order.company_id.account_fiscal_country_id

    @api.depends("company_id", "partner_id", "partner_id.reminder_date_before_receipt")
    def _compute_receipt_reminder_email(self):
        for order in self:
            order.receipt_reminder_email = order.partner_id.with_company(
                order.company_id
            ).receipt_reminder_email
            order.reminder_date_before_receipt = order.partner_id.with_company(
                order.company_id
            ).reminder_date_before_receipt

    @api.depends("line_ids", "line_ids.date_planned")
    def _compute_date_planned(self):
        """date_planned = the earliest date_planned across all order lines."""
        for order in self:
            if order.state == "cancel":
                order.date_planned = False
                continue

            dates_list = order.line_ids.filtered(
                lambda line: not line.display_type and line.date_planned
            ).mapped("date_planned")
            if dates_list:
                order.date_planned = min(dates_list)
            else:
                order.date_planned = False

    @api.depends("line_ids", "line_ids.product_id")
    def _compute_show_comparison(self):
        line_groupby_product = self.env["purchase.order.line"]._read_group(
            [
                ("product_id", "in", self.line_ids.product_id.ids),
                ("state", "=", "purchase"),
            ],
            ["product_id"],
            ["order_id:array_agg"],
        )
        order_by_product = {p: set(o_ids) for p, o_ids in line_groupby_product}
        for order in self:
            order.show_comparison = any(
                set(order.ids) != order_by_product[p]
                for p in order.line_ids.product_id
                if p in order_by_product
            )

    @api.depends("company_id", "currency_id", "line_ids.price_subtotal")
    def _compute_amounts(self):
        AccountTax = self.env["account.tax"]
        for order in self:
            order_lines = order.line_ids.filtered(lambda line: not line.display_type)
            base_lines = [
                line._prepare_base_line_for_taxes_computation() for line in order_lines
            ]
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
    @api.depends("company_id", "currency_id", "line_ids.price_subtotal")
    def _compute_tax_totals(self):
        AccountTax = self.env["account.tax"]
        for order in self:
            order_lines = order.line_ids.filtered(lambda line: not line.display_type)
            base_lines = [
                line._prepare_base_line_for_taxes_computation() for line in order_lines
            ]
            AccountTax._add_tax_details_in_base_lines(base_lines, order.company_id)
            AccountTax._round_base_lines_tax_details(base_lines, order.company_id)
            order.tax_totals = AccountTax._get_tax_totals_summary(
                base_lines=base_lines,
                currency=order.currency_id or order.company_id.currency_id,
                company=order.company_id,
            )
            # TODO should i bring back amount_total_cc? lmmg
            # if order.currency_id != order.company_currency_id:
            #     order.tax_totals["amount_total_cc"] = (
            #         f"({formatLang(self.env, order.amount_total_cc, currency_obj=self.company_currency_id)})"
            #     )

    @api.depends_context("show_total_amount")
    @api.depends("currency_id", "name", "partner_ref", "amount_total")
    def _compute_display_name(self):
        for order in self:
            name = order.name
            if order.partner_ref:
                name += " (" + order.partner_ref + ")"
            if self.env.context.get("show_total_amount") and order.amount_total:
                name += ": " + formatLang(
                    self.env, order.amount_total, currency_obj=order.currency_id
                )
            order.display_name = name

    @api.depends("line_ids.invoice_line_ids.move_id")
    def _compute_invoice_ids(self):
        for order in self:
            invoices = order.mapped("line_ids.invoice_line_ids.move_id")
            order.invoice_ids = invoices
            order.count_invoice_ids = len(invoices)

    @api.depends("state", "line_ids.qty_to_invoice")
    def _compute_invoice_state(self):
        confirmed_orders = self.filtered(lambda order: order.state == "purchase")
        (self - confirmed_orders).invoice_state = "no"
        if not confirmed_orders:
            return

        precision = self.env["decimal.precision"].precision_get("Product Unit")
        for order in confirmed_orders:
            if any(
                not float_is_zero(line.qty_to_invoice, precision_digits=precision)
                for line in order.line_ids.filtered(lambda line: not line.display_type)
            ):
                order.invoice_state = "to do"
            elif (
                all(
                    float_is_zero(line.qty_to_invoice, precision_digits=precision)
                    for line in order.line_ids.filtered(
                        lambda line: not line.display_type
                    )
                )
                and order.invoice_ids
            ):
                order.invoice_state = "done"
            else:
                order.invoice_state = "no"

    # ------------------------------------------------------------
    # ONCHANGE METHODS
    # ------------------------------------------------------------

    def onchange(self, values, field_names, fields_spec):
        """Override onchange to NOT update all date_planned on PO lines when date_planned
        on PO is updated by the change of date_planned on PO lines."""
        result = super().onchange(values, field_names, fields_spec)
        if (
            any(self._must_delete_date_planned(field) for field in field_names)
            and "value" in result
        ):
            for line in result["value"].get("line_ids", []):
                if line[0] == Command.UPDATE and "date_planned" in line[2]:
                    del line[2]["date_planned"]
        return result

    @api.onchange("partner_id")
    def onchange_partner_id_warning(self):
        if not self.partner_id or not self.env.user.has_group(
            "purchase.group_warning_purchase"
        ):
            return

        partner = self.partner_id
        # If partner has no warning, check its company
        if partner.purchase_warn == "no-message" and partner.parent_id:
            partner = partner.parent_id

        if partner.purchase_warn and partner.purchase_warn != "no-message":
            # Block if partner only has warning but parent company is blocked
            if (
                partner.purchase_warn != "block"
                and partner.parent_id
                and partner.parent_id.purchase_warn == "block"
            ):
                partner = partner.parent_id

            if partner.purchase_warn == "block":
                self.partner_id = False

            return {
                "warning": {
                    "title": _(f"Warning for {partner.name}"),
                    "message": partner.purchase_warn_msg,
                }
            }

    @api.onchange("date_planned")
    def _onchange_date_planned(self):
        if self.date_planned:
            self.line_ids.filtered(lambda line: not line.display_type).date_planned = (
                self.date_planned
            )

    @api.onchange("company_id", "fiscal_position_id")
    def _onchange_fiscal_position_id(self):
        """Trigger the recompute of the taxes if the fiscal position is changed"""
        self.line_ids._compute_tax_ids()

    # ------------------------------------------------------------
    # SEARCH METHODS
    # ------------------------------------------------------------

    def _search_is_late(self, operator, value):
        if operator not in ["=", "!="]:
            raise ValidationError(_("Unsupported operator"))

        purchase_order_ids = self._search(
            [("state", "=", "purchase"), ("date_planned", "<=", fields.Datetime.now())]
        )
        if operator == "=" and value or operator == "!=" and not value:
            purchase_lines_late = self.env["purchase.order.line"].search(
                [
                    ("order_id", "in", purchase_order_ids),
                    ("qty_transfered", "<", SQL("product_qty")),
                ]
            )
            return [("id", "in", purchase_lines_late.order_id.ids)]

        else:
            purchase_lines_on_time = self.env["purchase.order.line"]._search(
                [
                    ("order_id", "in", purchase_order_ids),
                    ("qty_transfered", ">=", SQL("product_qty")),
                ]
            )
            return [("id", "in", purchase_lines_on_time.order_id.ids)]

    # ------------------------------------------------------------
    # ACTION METHODS
    # ------------------------------------------------------------

    def action_send_rfq(self):
        """This function opens a window to compose an email with
        the edi purchase template message loaded by default"""
        self.ensure_one()
        lang = self.env.context.get("lang")
        ctx = dict(self.env.context or {})
        ctx.update(
            {
                "default_model": "purchase.order",
                "default_res_ids": self.ids,
                "default_composition_mode": "comment",
                "default_email_layout_xmlid": "mail.mail_notification_layout_with_responsible_signature",
                "email_notification_allow_footer": True,
                "hide_mail_template_management_options": True,
                "force_email": True,
                "model_description": self.type_name,
                "mark_rfq_as_sent": True,
            }
        )

        mail_template = self._get_mail_template()
        if mail_template:
            ctx.update(
                {
                    "default_template_id": mail_template.id,
                }
            )

        # In the case of a RFQ or a PO, we want the "View..." button in line with the state of the
        # object. Therefore, we pass the model description in the context, in the language in which
        # the template is rendered.
        if mail_template and mail_template.lang:
            lang = mail_template._render_lang(self.ids)[self.id]

        compose_form = self._get_mail_compose_form()
        self = self.with_context(lang=lang)
        action = {
            "name": _("Send by Email"),
            "type": "ir.actions.act_window",
            "res_model": "mail.compose.message",
            "view_mode": "form",
            "views": [(compose_form, "form")],
            "view_id": compose_form,
            "target": "new",
            "context": ctx,
        }
        return action

    def action_bill_matching(self):
        self.ensure_one()
        return {
            "name": _("Bill Matching"),
            "type": "ir.actions.act_window",
            "res_model": "purchase.bill.line.match",
            "views": [
                (self.env.ref("purchase.purchase_bill_line_match_tree").id, "list")
            ],
            "domain": [
                ("company_id", "in", self.env.company.ids),
                ("partner_id", "=", self.partner_id.id),
                ("purchase_order_id", "in", [self.id, False]),
            ],
        }

    def action_purchase_comparison(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "purchase.action_purchase_history"
        )
        action["display_name"] = _(f"Purchase Comparison for {self.display_name}")
        action["domain"] = [("product_id", "in", self.line_ids.product_id.ids)]
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

    def action_view_invoice(self, invoices=False):
        if not invoices:
            self.invalidate_model(["invoice_ids"])
            invoices = self.invoice_ids

        action = self.env["ir.actions.act_window"]._for_xml_id(
            "account.action_move_in_invoice_type"
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
            "default_move_type": "in_invoice",
        }
        if len(self) == 1:
            context.update(
                {
                    "default_partner_id": self.partner_id.id,
                    "default_invoice_payment_term_id": self.payment_term_id.id
                    or self.partner_id.property_supplier_payment_term_id.id
                    or self.env["account.move"]
                    .default_get(["invoice_payment_term_id"])
                    .get("invoice_payment_term_id"),
                    "default_invoice_origin": self.name,
                }
            )
        action["context"] = context
        return action

    def action_acknowledge(self):
        self.write({"acknowledged": True})

    def action_cancel(self):
        self._can_cancel_except_locked()
        self._can_cancel_except_invoiced()
        inv = self.invoice_ids.filtered(lambda i: i.state == "draft")
        inv.button_cancel()
        self.write({"state": "cancel"})
        return True

    def action_confirm(self):
        self._can_confirm_proper_state()
        self._can_confirm_has_lines()
        self._can_confirm_lines_have_product()
        for order in self:
            if order._approval_allowed():
                order.write(self._prepare_action_confirm_write_vals())
                order.line_ids._validate_analytic_distribution()
                order._create_supplier_for_product()

                if order.company_id.po_lock == "lock":
                    order.action_lock()
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
        self.write({"state": "draft"})
        return {}

    def action_lock(self):
        self.write({"locked": True, "priority": "0"})

    def action_unlock(self):
        if self.company_id.po_lock == "lock":
            raise UserError(
                _(
                    "Unlocking the order is not allowed as 'Lock Confirmed Orders' is enabled."
                )
            )

        self.write({"locked": False})

    def print_quotation(self):
        self.filtered(lambda order: order.state == "draft").write(
            {"printed_before": True}
        )
        return self.env.ref("purchase.report_purchase_quotation").report_action(self)

    # ------------------------------------------------------------
    # MAIL.THREAD
    # ------------------------------------------------------------

    def message_post(self, **kwargs):
        if self.env.context.get("mark_rfq_as_sent"):
            self.filtered(lambda order: order.state == "draft").write({"sent": True})
            kwargs["notify_author_mention"] = kwargs.get("notify_author_mention", True)
        return super().message_post(**kwargs)

    def _notify_get_recipients_groups(self, message, model_description, msg_vals=False):
        # Tweak "view document" button for portal customers,
        # calling directly routes for confirm specific to PO model.
        groups = super()._notify_get_recipients_groups(
            message, model_description, msg_vals=msg_vals
        )
        if not self:
            return groups

        self.ensure_one()
        try:
            customer_portal_group = next(
                group for group in groups if group[0] == "portal_customer"
            )
        except StopIteration:
            pass

        else:
            access_opt = customer_portal_group[2].setdefault("button_access", {})
            if self.env.context.get("is_reminder"):
                access_opt["title"] = _("View")
            else:
                access_opt["title"] = self.type_name
                access_opt["url"] = self.get_confirm_url()

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
            msg_vals=msg_vals,
            model_description=model_description,
            force_email_company=force_email_company,
            force_email_lang=force_email_lang,
        )
        subtitles = [render_context["record"].name]
        # don't show price on RFQ mail
        if self.state == "draft":
            subtitles.append(
                _(
                    "Order\N{NO-BREAK SPACE}due\N{NO-BREAK SPACE}%(date)s",
                    date=format_date(
                        self.env, self.date_order, lang_code=render_context.get("lang")
                    ),
                )
            )
        else:
            subtitles.append(
                format_amount(
                    self.env,
                    self.amount_total,
                    self.currency_id,
                    lang_code=render_context.get("lang"),
                )
            )
        render_context["subtitles"] = subtitles
        return render_context

    def _track_subtype(self, init_values):
        self.ensure_one()
        if "state" in init_values and self.state == "purchase":
            if init_values["state"] == "to approve":
                return self.env.ref("purchase.mt_rfq_approved")

            return self.env.ref("purchase.mt_rfq_confirmed")

        elif "state" in init_values and self.state == "to approve":
            return self.env.ref("purchase.mt_rfq_confirmed")

        elif "locked" in init_values and self.locked:
            return self.env.ref("purchase.mt_rfq_done")

        elif "sent" in init_values and self.sent:
            return self.env.ref("purchase.mt_rfq_sent")

        return super()._track_subtype(init_values)

    def _create_update_date_activity(self, updated_dates):
        note = Markup("<p>%s</p>\n") % _(
            "%s modified receipt dates for the following products:",
            self.partner_id.name,
        )
        for line, date in updated_dates:
            note += Markup("<p> - %s</p>\n") % _(
                "%(product)s from %(original_receipt_date)s to %(new_receipt_date)s",
                product=line.product_id.display_name,
                original_receipt_date=line.date_planned.date(),
                new_receipt_date=date.date(),
            )
        activity = self.activity_schedule(
            "mail.mail_activity_data_warning",
            summary=_("Date Updated"),
            user_id=self.user_id.id,
        )
        # add the note after we post the activity because the note can be soon
        # changed when updating the date of the next PO line. So instead of
        # sending a mail with incomplete note, we send one with no note.
        activity.note = note
        return activity

    def _update_update_date_activity(self, updated_dates, activity):
        for line, date in updated_dates:
            activity.note += Markup("<p> - %s</p>\n") % _(
                "%(product)s from %(original_receipt_date)s to %(new_receipt_date)s",
                product=line.product_id.display_name,
                original_receipt_date=line.date_planned.date(),
                new_receipt_date=date.date(),
            )

    # ------------------------------------------------------------
    # CATALOGUE MIXIN
    # ------------------------------------------------------------

    def action_add_from_catalog(self):
        res = super().action_add_from_catalog()
        if res["context"].get("product_catalog_order_model") == "purchase.order":
            res["search_view_id"] = [
                self.env.ref("purchase.product_view_search_catalog").id,
                "search",
            ]
        kanban_view_id = self.env.ref(
            "purchase.product_view_kanban_catalog_purchase_only"
        ).id
        res["views"][0] = (kanban_view_id, "kanban")
        res["context"]["partner_id"] = self.partner_id.id
        return res

    def _default_order_line_values(self, child_field=False):
        default_data = super()._default_order_line_values(child_field)
        new_default_data = self.env[
            "purchase.order.line"
        ]._get_product_catalog_lines_data()
        return {**default_data, **new_default_data}

    def _update_order_line_info(self, product_id, quantity, **kwargs):
        """Update purchase order line information for a given product or create
        a new one if none exists yet.
        :param int product_id: The product, as a `product.product` id.
        :return: The unit price of the product, based on the pricelist of the
                 purchase order and the quantity selected.
        :rtype: float"""
        self.ensure_one()
        pol = self.line_ids.filtered(lambda line: line.product_id.id == product_id)
        if pol:
            if quantity != 0:
                pol.product_qty = quantity
            elif self.state == "draft":
                price_unit = self._get_product_price_and_data(pol.product_id)["price"]
                pol.unlink()
                return price_unit

            else:
                pol.product_qty = 0
        elif quantity > 0:
            pol = self.env["purchase.order.line"].create(
                {
                    "order_id": self.id,
                    "product_id": product_id,
                    "product_qty": quantity,
                    "sequence": (
                        (self.line_ids and self.line_ids[-1].sequence + 1) or 10
                    ),  # put it at the end of the order
                }
            )
            seller = pol.product_id._select_seller(
                partner_id=pol.partner_id,
                quantity=pol.product_qty,
                date=pol.order_id.date_order
                and pol.order_id.date_order.date()
                or fields.Date.context_today(pol),
                uom_id=pol.product_uom_id,
            )
            if seller:
                # Fix the PO line's price on the seller's one.
                pol.price_unit = seller.price_discounted
        return pol.price_unit_discounted_taxexc

    def _get_action_add_from_catalog_extra_context(self):
        return {
            **super()._get_action_add_from_catalog_extra_context(),
            "display_uom": self.env.user.has_group("uom.group_uom"),
            "precision": self.env["decimal.precision"].precision_get("Product Unit"),
            "product_catalog_currency_id": self.currency_id.id,
            "product_catalog_digits": self.line_ids._fields["price_unit"].get_digits(
                self.env
            ),
            "search_default_seller_ids": self.partner_id.name,
        }

    def _get_product_catalog_domain(self):
        return expression.AND(
            [super()._get_product_catalog_domain(), [("purchase_ok", "=", True)]]
        )

    def _get_product_catalog_order_data(self, products, **kwargs):
        res = super()._get_product_catalog_order_data(products, **kwargs)
        for product in products:
            res[product.id] |= self._get_product_price_and_data(product)
        return res

    def _get_product_catalog_record_lines(self, product_ids, child_field=False):
        grouped_lines = defaultdict(lambda: self.env["purchase.order.line"])
        for line in self.line_ids:
            if line.display_type or line.product_id.id not in product_ids:
                continue

            grouped_lines[line.product_id] |= line
        return grouped_lines

    def _is_readonly(self):
        """Return whether the purchase order is read-only or not based on the state.
        A purchase order is considered read-only if its state is "cancel".

        :return: Whether the purchase order is read-only or not.
        :rtype: bool"""
        self.ensure_one()
        return self.state == "cancel" or self.locked

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    def _create_downpayments(self, line_vals):
        self.ensure_one()
        if not any(line.display_type and line.is_downpayment for line in self.line_ids):
            section_line = self.line_ids.create(
                self._prepare_down_payment_section_values()
            )
        else:
            section_line = self.line_ids.filtered(
                lambda line: line.display_type and line.is_downpayment
            )
        vals = [
            {
                **line_val,
                "sequence": section_line.sequence + i,
            }
            for i, line_val in enumerate(line_vals, start=1)
        ]
        downpayment_lines = self.env["purchase.order.line"].create(vals)
        # a simple concatenation would cause all line_ids to recompute, we do not want it to happen
        self.line_ids = [Command.link(line_id) for line_id in downpayment_lines.ids]
        return downpayment_lines

    def create_invoice(self):
        """Create the invoice associated to the PO."""
        if not self.env["account.move"].has_access("create"):
            try:
                self.check_access("write")
            except AccessError:
                return self.env["account.move"]

        precision = self.env["decimal.precision"].precision_get("Product Unit")
        # 1) Prepare invoice vals and clean-up the section lines
        invoice_vals_list = []
        sequence = 10
        for order in self:
            if order.partner_id.lang:
                order = order.with_context(lang=order.partner_id.lang)
            order = order.with_company(order.company_id)
            invoice_vals = order._prepare_invoice_vals()
            pending_section = None
            for line in order.line_ids:
                # Only invoice the section if one of its lines is invoiceable
                if line.display_type == "line_section":
                    pending_section = line
                    continue

                if not float_is_zero(line.qty_to_invoice, precision_digits=precision):
                    if pending_section:
                        line_vals = pending_section._prepare_aml_vals()
                        line_vals.update({"sequence": sequence})
                        invoice_vals["invoice_line_ids"].append(
                            Command.create(line_vals)
                        )
                        sequence += 1
                        pending_section = None
                    line_vals = line._prepare_aml_vals()
                    line_vals.update({"sequence": sequence})
                    invoice_vals["invoice_line_ids"].append(Command.create(line_vals))
                    sequence += 1
            invoice_vals_list.append(invoice_vals)

        if not invoice_vals_list:
            raise UserError(
                _(
                    "There is no invoiceable line. If a product has a control policy based on "
                    "received quantity, please make sure that a quantity has been received."
                )
            )

        # 2) group by (company_id, partner_id, currency_id) for batch creation
        new_invoice_vals_list = []
        for _grouping_keys, invoices in groupby(
            invoice_vals_list,
            key=lambda x: (
                x.get("company_id"),
                x.get("partner_id"),
                x.get("currency_id"),
            ),
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
        invoices = self.env["account.move"]
        AccountMove = self.env["account.move"].with_context(
            default_move_type="in_invoice"
        )
        for vals in invoice_vals_list:
            invoices |= AccountMove.with_company(vals["company_id"]).create(vals)

        # 4) Some moves might actually be refunds: convert them if the total amount is negative
        # We do this after the moves have been created since we need taxes, etc. to know if the total
        # is actually negative or not
        invoices.filtered(
            lambda m: m.currency_id.round(m.amount_total) < 0
        ).action_switch_move_type()

    def _create_supplier_for_product(self):
        # Add the partner in the supplier list of the product if the supplier is not registered for
        # this product. We limit to 10 the number of suppliers for a product to avoid the mess that
        # could be caused for some generic products ("Miscellaneous").
        for line in self.line_ids:
            # Do not add a contact as a supplier
            partner = (
                self.partner_id
                if not self.partner_id.parent_id
                else self.partner_id.parent_id
            )
            already_seller = (
                partner | self.partner_id
            ) & line.product_id.seller_ids.mapped("partner_id")
            if (
                line.product_id
                and not already_seller
                and len(line.product_id.seller_ids) <= 10
            ):
                price = line.price_unit
                # Compute the price for the template's UoM, because the supplier's UoM is related to that UoM.
                if line.product_id.product_tmpl_id.uom_id != line.product_uom_id:
                    default_uom = line.product_id.product_tmpl_id.uom_id
                    price = line.product_uom_id._compute_price(price, default_uom)

                supplierinfo = self._prepare_supplier_info(
                    partner, line, price, line.currency_id
                )
                # In case the order partner is a contact address, a new supplierinfo is created on
                # the parent company. In this case, we keep the product name and code.
                seller = line.product_id._select_seller(
                    partner_id=line.partner_id,
                    quantity=line.product_qty,
                    date=line.order_id.date_order and line.order_id.date_order.date(),
                    uom_id=line.product_uom_id,
                )
                if seller:
                    supplierinfo["product_name"] = seller.product_name
                    supplierinfo["product_code"] = seller.product_code
                    supplierinfo["product_uom_id"] = line.product_uom_id.id
                vals = {
                    "seller_ids": [(0, 0, supplierinfo)],
                }
                # supplier info should be added regardless of the user access rights
                line.product_id.product_tmpl_id.sudo().write(vals)

    def _merge_alternative_po(self, rfqs):
        pass

    # def action_merge(self):
    def merge_orders(self):
        all_origin = []
        all_vendor_references = []
        rfq_to_merge = self.filtered(lambda r: r.state in ["draft", "sent"])

        if len(rfq_to_merge) < 2:
            raise UserError(
                _(
                    "Please select at least two purchase orders with state RFQ and RFQ sent to merge."
                )
            )

        rfqs_grouped = defaultdict(lambda: self.env["purchase.order"])
        for rfq in rfq_to_merge:
            key = self._prepare_grouped_data(rfq)
            rfqs_grouped[key] += rfq

        bunches_of_rfq_to_be_merge = list(rfqs_grouped.values())
        if all(len(rfq_bunch) == 1 for rfq_bunch in list(bunches_of_rfq_to_be_merge)):
            raise UserError(
                _(
                    "In selected purchase order to merge these details must be same\nVendor, currency, destination, dropship address and agreement"
                )
            )

        bunches_of_rfq_to_be_merge = [
            rfqs for rfqs in bunches_of_rfq_to_be_merge if len(rfqs) > 1
        ]
        for rfqs in bunches_of_rfq_to_be_merge:
            if len(rfqs) <= 1:
                continue

            oldest_rfq = min(rfqs, key=lambda r: r.date_order)
            if oldest_rfq:
                # Merge RFQs into the oldest purchase order
                rfqs -= oldest_rfq
                for rfq_line in rfqs.line_ids:
                    existing_line = oldest_rfq.line_ids.filtered(
                        lambda l: l.display_type not in ["line_note", "line_section"]
                        and l.product_id == rfq_line.product_id
                        and l.product_uom_id == rfq_line.product_uom_id
                        and l.analytic_distribution == rfq_line.analytic_distribution
                        and l.discount == rfq_line.discount
                        and abs(l.date_planned - rfq_line.date_planned).total_seconds()
                        <= 86400  # 24 hours in seconds
                    )
                    if len(existing_line) > 1:
                        existing_line[0].product_qty += sum(
                            existing_line[1:].mapped("product_qty")
                        )
                        existing_line[1:].unlink()
                        existing_line = existing_line[0]

                    if existing_line:
                        existing_line._merge_po_line(rfq_line)
                    else:
                        rfq_line.order_id = oldest_rfq

                # Merge source documents and vendor references
                all_origin = rfqs.mapped("origin")
                all_vendor_references = rfqs.mapped("partner_ref")
                oldest_rfq.origin = ", ".join(
                    filter(None, [oldest_rfq.origin, *all_origin])
                )
                oldest_rfq.partner_ref = ", ".join(
                    filter(None, [oldest_rfq.partner_ref, *all_vendor_references])
                )
                rfq_names = rfqs.mapped("name")
                merged_names = ", ".join(rfq_names)
                oldest_rfq_message = _(
                    "RFQ merged with %(oldest_rfq_name)s and %(cancelled_rfq)s",
                    oldest_rfq_name=oldest_rfq.name,
                    cancelled_rfq=merged_names,
                )
                for rfq in rfqs:
                    cancelled_rfq_message = _(
                        "RFQ merged with %s", oldest_rfq._get_html_link()
                    )
                    rfq.message_post(body=cancelled_rfq_message)
                oldest_rfq.message_post(body=oldest_rfq_message)
                rfqs.filtered(lambda r: r.state != "cancel").action_cancel()
                oldest_rfq._merge_alternative_po(rfqs)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": _("purchase orders merged"),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def _send_reminder_mail(self, send_single=False):
        if not self.env.user.has_group("purchase.group_send_reminder"):
            return

        template = self.env.ref(
            "purchase.email_template_edi_purchase_reminder", raise_if_not_found=False
        )
        if template:
            orders = self if send_single else self._get_orders_to_remind()
            for order in orders:
                date = order.date_planned
                if date and (
                    send_single
                    or (
                        date - relativedelta(days=order.reminder_date_before_receipt)
                    ).date()
                    == fields.Date.today()
                ):
                    if send_single:
                        return order._send_reminder_open_composer(template.id)

                    else:
                        order.with_context(is_reminder=True).message_post_with_source(
                            template,
                            email_layout_xmlid="mail.mail_notification_layout_with_responsible_signature",
                            subtype_xmlid="mail.mt_comment",
                        )

    def _send_reminder_open_composer(self, template_id):
        self.ensure_one()
        try:
            compose_form = self.env["ir.model.data"]._xmlid_lookup(
                "mail.email_compose_message_wizard_form"
            )[1]
        except ValueError:
            compose_form = False
        ctx = dict(self.env.context or {})
        ctx.update(
            {
                "default_model": "purchase.order",
                "default_res_ids": self.ids,
                "default_template_id": template_id,
                "default_composition_mode": "comment",
                "default_email_layout_xmlid": "mail.mail_notification_layout_with_responsible_signature",
                "force_email": True,
                "mark_rfq_as_sent": True,
            }
        )
        lang = self.env.context.get("lang")
        if {"default_template_id", "default_model", "default_res_id"} <= ctx.keys():
            template = self.env["mail.template"].browse(ctx["default_template_id"])
            if template and template.lang:
                lang = template._render_lang([ctx["default_res_id"]])[
                    ctx["default_res_id"]
                ]
        self = self.with_context(lang=lang)
        ctx["model_description"] = _("Purchase Order")
        return {
            "name": _("Compose Email"),
            "type": "ir.actions.act_window",
            "res_model": "mail.compose.message",
            "view_mode": "form",
            "views": [(compose_form, "form")],
            "view_id": compose_form,
            "target": "new",
            "context": ctx,
        }

    def send_reminder_preview(self):
        self.ensure_one()
        if not self.env.user.has_group("purchase.group_send_reminder"):
            return

        template = self.env.ref(
            "purchase.email_template_edi_purchase_reminder", raise_if_not_found=False
        )
        if template and self.env.user.email and self.id:
            template.with_context(is_reminder=True).send_mail(
                self.id,
                force_send=True,
                raise_exception=False,
                email_layout_xmlid="mail.mail_notification_layout_with_responsible_signature",
                email_values={"email_to": self.env.user.email, "recipient_ids": []},
            )
            return {
                "toast_message": escape(
                    _("A sample email has been sent to %s.", self.env.user.email)
                )
            }

    def _update_order_lines_date_planned(self, updated_dates):
        activity = self.env["mail.activity"].search(
            [
                ("summary", "=", _("Date Updated")),
                ("res_model_id", "=", "purchase.order"),
                ("res_id", "=", self.id),
                ("user_id", "=", self.user_id.id),
            ],
            limit=1,
        )
        if activity:
            self._update_update_date_activity(updated_dates, activity)
        else:
            self._create_update_date_activity(updated_dates)

        for line, date in updated_dates:
            line._update_date_planned(date)

    def get_acknowledge_url(self):
        return self.get_portal_url(query_string="&acknowledge=True")

    def get_approval_category(self):
        return self.env.ref("purchase.approval_category_purchase")

    def get_confirm_url(self, confirm_type=None):
        """Create url for confirm reminder or purchase reception email for sending
        in mail. Unsuported anymore. We only use the acknowledge mechanism. Keep it
        for backward compatibility"""
        if confirm_type in ["reminder", "reception", "decline"]:
            return self.get_acknowledge_url()

        return self.get_portal_url()

    def _get_edi_builders(self):
        return []

    def _get_mail_compose_form(self):
        ir_model_data = self.env["ir.model.data"]
        try:
            compose_form = ir_model_data._xmlid_lookup(
                "mail.email_compose_message_wizard_form"
            )[1]
        except ValueError:
            compose_form = False
        return compose_form

    def _get_mail_template(self):
        ir_model_data = self.env["ir.model.data"]
        try:
            if self.env.context.get("send_rfq", False):
                template_id = ir_model_data._xmlid_lookup(
                    "purchase.email_template_edi_purchase"
                )[1]
            else:
                template_id = ir_model_data._xmlid_lookup(
                    "purchase.email_template_edi_purchase_done"
                )[1]
        except ValueError:
            template_id = False
        return template_id

    @api.model
    def _get_orders_to_remind(self):
        """When auto sending a reminder mail, only send for unconfirmed purchase
        order and not all products are service."""
        return self.search(
            [
                ("partner_id", "!=", False),
                ("state", "=", "purchase"),
                ("acknowledged", "=", False),
                ("receipt_reminder_email", "=", True),
            ]
        ).filtered(
            lambda order: order.mapped("line_ids.product_id.product_tmpl_id.type")
            != ["service"]
        )

    def _get_product_price_and_data(self, product):
        """Fetch the product's data used by the purchase's catalog.

        :return: the product's price and, if applicable, the minimum quantity to
                 buy and the product's packaging data.
        :rtype: dict"""
        self.ensure_one()
        product_infos = {
            "price": product.standard_price,
            "uom": {
                "display_name": product.uom_id.display_name,
                "id": product.uom_id.id,
            },
        }
        if product.purchase_line_warn_msg:
            product_infos["warning"] = product.purchase_line_warn_msg
        if product.purchase_line_warn == "block":
            product_infos["readOnly"] = True
        params = {"order_id": self}
        # Check if there is a price and a minimum quantity for the order's vendor.
        seller = product._select_seller(
            partner_id=self.partner_id,
            quantity=None,
            date=self.date_order and self.date_order.date(),
            uom_id=product.uom_id,
            ordered_by="min_qty",
            params=params,
        )
        if seller:
            product_infos.update(
                price=seller.price_discounted,
                min_qty=seller.min_qty,
            )
        return product_infos

    def _get_report_base_filename(self):
        self.ensure_one()
        return f"Purchase Order-{self.name}"

    def get_timezone(self):
        """Returns the timezone of the order's user or the company's partner
        or UTC if none of them are set."""
        self.ensure_one()
        return timezone(self.user_id.tz or self.company_id.partner_id.tz or "UTC")

    def get_update_url(self):
        """Create portal url for user to update the scheduled date on purchase
        order lines."""
        update_param = url_encode({"update": "True"})
        return self.get_portal_url(query_string="&%s" % update_param)

    def _prepare_action_confirm_write_vals(self):
        """Prepare the purchase order confirmation values.

        Note: self can contain multiple records.

        :return: Purchase Order confirmation values
        :rtype: dict"""
        return {"state": "purchase", "date_approve": fields.Datetime.now()}

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

    def _prepare_down_payment_section_values(self):
        self.ensure_one()
        context = {"lang": self.partner_id.lang}
        res = {
            "order_id": self.id,
            "display_type": "line_section",
            "name": _("Down Payments"),
            "is_downpayment": True,
            "product_qty": 0.0,
            "sequence": (self.line_ids[-1:].sequence or 9) + 1,
        }
        del context
        return res

    def _prepare_grouped_data(self, rfq):
        return (rfq.partner_id.id, rfq.currency_id.id, rfq.dest_address_id.id)

    def _prepare_invoice_vals(self):
        """Prepare the dict of values to create the new invoice for a purchase order."""
        self.ensure_one()
        move_type = self._context.get("default_move_type", "in_invoice")
        partner_invoice = self.env["res.partner"].browse(
            self.partner_id.address_get(["invoice"])["invoice"]
        )
        partner_bank_id = (
            self.partner_id.commercial_partner_id.bank_ids.filtered_domain(
                [("company_id", "in", (False, self.company_id.id))]
            )[:1]
        )
        values = {
            "move_type": move_type,
            "company_id": self.company_id.id,
            "currency_id": self.currency_id.id,
            "partner_id": partner_invoice.id,
            "partner_bank_id": partner_bank_id.id,
            "fiscal_position_id": (
                self.fiscal_position_id
                or self.fiscal_position_id._get_fiscal_position(partner_invoice)
            ).id,
            "invoice_payment_term_id": self.payment_term_id.id,
            "invoice_user_id": self.user_id.id,
            "invoice_origin": self.name,
            "ref": self.partner_ref or "",
            "narration": self.notes,
            "payment_reference": self.partner_ref or "",
            "invoice_line_ids": [],
        }
        if self.journal_id:
            values["journal_id"] = self.journal_id.id
        return values

    def _prepare_supplier_info(self, partner, line, price, currency):
        # Prepare supplierinfo data when adding a product
        return {
            "partner_id": partner.id,
            "currency_id": currency.id,
            "sequence": (
                max(line.product_id.seller_ids.mapped("sequence")) + 1
                if line.product_id.seller_ids
                else 1
            ),
            "price": price,
            "discount": line.discount,
            "min_qty": 1.0,
            "delay": 0,
        }

    @api.model
    def _prepare_dashboard(self):
        """This function returns the values to populate the custom dashboard in
        the purchase order views."""
        self.browse().check_access("read")
        result = {
            "global": {
                "draft": {"all": 0, "priority": 0},
                "sent": {"all": 0, "priority": 0},
                "late": {"all": 0, "priority": 0},
                "not_acknowledged": {"all": 0, "priority": 0},
                "late_receipt": {"all": 0, "priority": 0},
                "days_to_order": 0,
            },
            "my": {
                "draft": {"all": 0, "priority": 0},
                "sent": {"all": 0, "priority": 0},
                "late": {"all": 0, "priority": 0},
                "not_acknowledged": {"all": 0, "priority": 0},
                "late_receipt": {"all": 0, "priority": 0},
                "days_to_order": 0,
            },
            "days_to_purchase": 0,
        }

        def _update(key, dict_to_update, group):
            for priority, user_id, count in group:
                my = user_id == self.env.user
                dict_to_update["global"][key]["all"] += count
                if priority != "0":
                    dict_to_update["global"][key]["priority"] += count
                if not my:
                    continue

                dict_to_update["my"][key]["all"] += count
                if priority != "0":
                    dict_to_update["my"][key]["priority"] += count

        # easy counts
        groupby = ["priority", "user_id"]
        aggregate = ["id:count_distinct"]
        rfq_draft_domain = [("state", "=", "draft")]
        rfq_draft_group = self.env["purchase.order"]._read_group(
            rfq_draft_domain, groupby, aggregate
        )
        _update("draft", result, rfq_draft_group)

        rfq_sent_domain = [("sent", "=", True)]
        rfq_sent_group = self.env["purchase.order"]._read_group(
            rfq_sent_domain, groupby, aggregate
        )
        _update("sent", result, rfq_sent_group)

        rfq_late_domain = [
            ("state", "in", ["draft", "to approve"]),
            ("date_order", "<", fields.Datetime.now()),
        ]
        rfq_late_group = self.env["purchase.order"]._read_group(
            rfq_late_domain, groupby, aggregate
        )
        _update("late", result, rfq_late_group)

        rfq_not_acknowledge = [("state", "=", "purchase"), ("acknowledged", "=", False)]
        rfq_not_acknowledge_group = self.env["purchase.order"]._read_group(
            rfq_not_acknowledge, groupby, aggregate
        )
        _update("not_acknowledged", result, rfq_not_acknowledge_group)

        rfq_late_receipt = [("is_late", "=", True)]
        rfq_late_receipt_group = self.env["purchase.order"]._read_group(
            rfq_late_receipt, groupby, aggregate
        )
        _update("late_receipt", result, rfq_late_receipt_group)

        three_months_ago = fields.Datetime.to_string(
            fields.Datetime.now() - relativedelta(months=3)
        )
        purchases = self.env["purchase.order"].search_fetch(
            [
                ("state", "=", "purchase"),
                ("create_date", ">=", three_months_ago),
                ("date_approve", "!=", False),
            ],
            ["create_date", "date_approve", "user_id"],
        )
        global_deliveries_seconds = 0
        my_deliveries_seconds = 0
        my_deliveries_count = 0
        for po in purchases:
            delivery_seconds = (po.date_approve - po.create_date).total_seconds()
            global_deliveries_seconds += delivery_seconds
            if po.user_id == self.env.user:
                my_deliveries_seconds += delivery_seconds
                my_deliveries_count += 1

        avg_global_deliveries_seconds = (
            global_deliveries_seconds / len(purchases) if purchases else 0
        )
        avg_my_deliveries_seconds = (
            my_deliveries_seconds / my_deliveries_count if my_deliveries_count else 0
        )
        result["global"]["days_to_order"] = float_repr(
            avg_global_deliveries_seconds / 60 / 60 / 24, precision_digits=2
        )
        result["my"]["days_to_order"] = float_repr(
            avg_my_deliveries_seconds / 60 / 60 / 24, precision_digits=2
        )
        return result

    # ------------------------------------------------------------
    # VALIDATIONS
    # ------------------------------------------------------------

    def _approval_allowed(self):
        """Returns whether the order qualifies to be approved by the current user"""
        self.ensure_one()
        return not self.company_id.po_approval or self.approval_state == "approved"

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
        orders_locked = self.filtered(lambda order: order.locked)
        if orders_locked:
            raise UserError(
                _("You cannot cancel a locked order. Please unlock it first.")
            )

    def _can_cancel_except_invoiced(self):
        """Returns whether the order qualifies to be canceled by the current user"""
        orders_with_invoices = self.filtered(
            lambda order: any(i.state == "posted" for i in order.invoice_ids)
        )
        if orders_with_invoices:
            raise UserError(
                _(
                    "Unable to cancel purchase order(s): %s. "
                    "You must first cancel their related vendor bills.",
                    format_list(self.env, orders_with_invoices.mapped("display_name")),
                )
            )

    def _must_delete_date_planned(self, field_name):
        # To be overridden
        return field_name == "line_ids"
