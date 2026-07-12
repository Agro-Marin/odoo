from urllib.parse import urlencode

from dateutil.relativedelta import relativedelta
from markupsafe import Markup, escape
from pytz import timezone

from odoo import api, fields, models
from odoo.exceptions import AccessDenied, UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.libs.numbers.float_utils import float_repr
from odoo.tools import (
    SQL,
    OrderedSet,
    format_amount,
    format_date,
    formatLang,
)
from odoo.tools.translate import _

from odoo.addons.purchase import const


class PurchaseOrder(models.Model):
    _name = "purchase.order"
    _inherit = [
        "order.mixin",
        "order.amount.mixin",
        "order.invoice.mixin",
        "order.merge.mixin",
        "account.document.import.mixin",
    ]
    _description = "Purchase Order"
    _check_company_auto = True
    _order = "priority desc, id desc"

    def _get_rec_search_base_fields(self):
        return ["name", "partner_ref"]

    # ------------------------------------------------------------
    # ORDER MIXIN ROUTING HOOKS
    # ------------------------------------------------------------

    def _get_order_type(self):
        return "purchase"

    def _get_catalog_product_ok_field(self):
        return "purchase_ok"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    partner_id = fields.Many2one(
        string="Vendor",
        help="You can find a vendor by its Name, TIN, Email or Internal Reference.",
    )
    partner_bill_count = fields.Integer(
        related="partner_id.supplier_invoice_count",
    )
    dest_address_id = fields.Many2one(
        comodel_name="res.partner",
        string="Dropship Address",
        check_company=True,
        index=True,
        tracking=True,
        help="Put an address if you want to deliver directly from the vendor to the customer. "
        "Otherwise, keep empty to deliver to your own company.",
    )
    # Only ``string`` and ``domain`` differ from ``order.mixin.user_id``; the
    # rest (compute, store, precompute, readonly, index, tracking) is inherited.
    user_id = fields.Many2one(
        string="Buyer",
        domain=lambda self: """
            [
                ('all_group_ids', 'in', {}),
                ('share', '=', False),
                ('company_ids', '=', company_id),
            ]
        """.format(
            self.env.ref("purchase.group_purchase_user").ids,
        ),
    )
    # Only ``string``, ``domain`` and ``help`` differ from
    # ``order.mixin.journal_id``; the rest is inherited.
    journal_id = fields.Many2one(
        domain=[("type", "=", "purchase")],
        help="If set, the PO will invoice in this journal; "
        "otherwise the purchase journal with the lowest sequence is used.",
    )
    # Same keys as ``order.mixin.state`` (draft/done/cancel), only relabelled.
    # The rest is inherited.
    state = fields.Selection(
        selection=const.ORDER_STATE,
    )
    tag_ids = fields.Many2many(
        comodel_name="srm.tag",
        relation="purchase_order_tag_rel",
        column1="order_id",
        column2="tag_id",
        string="Tags",
    )
    date_validity = fields.Date(
        help="Validity of the RFQ, after which it expires.",
    )
    date_confirmed = fields.Datetime(
        help="Date when the purchase order was confirmed.",
    )
    date_calendar_start = fields.Datetime(
        compute="_compute_date_calendar_start",
        store=True,
        readonly=True,
    )

    # Order line block
    line_ids = fields.One2many(
        comodel_name="purchase.order.line",
        inverse_name="order_id",
        string="Order Lines",
        copy=True,
    )
    product_id = fields.Many2one(
        related="line_ids.product_id",
        comodel_name="product.product",
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
    # Invoice block
    invoice_ids = fields.Many2many(string="Bills")
    invoice_count = fields.Integer(string="Bill Count")

    origin = fields.Char(
        string="Source",
        help="Reference of the document that generated this purchase order "
        "request (e.g. a sales order)",
    )
    partner_ref = fields.Char(
        string="Vendor Reference",
        help="Reference of the sales order or bid sent by the vendor. "
        "It's used to do the matching when you receive the "
        "products as this reference is usually written on the "
        "delivery order sent by your vendor.",
    )
    acknowledged = fields.Boolean(
        help="It indicates that the vendor has acknowledged the receipt of the purchase order.",
    )
    sent = fields.Boolean(
        help="The RFQ has been sent to the vendor.",
    )
    printed_before = fields.Boolean(
        help="The RFQ has already been printed.",
    )
    show_comparison = fields.Boolean(
        string="Show Comparison",
        compute="_compute_show_comparison",
    )
    purchase_warning_text = fields.Text(
        string="Purchase Warning",
        compute="_compute_purchase_warning_text",
        help="Internal warning for the partner or the products as set by the user.",
    )
    duplicated_order_ids = fields.Many2many(
        comodel_name="purchase.order",
        compute="_compute_duplicated_order_ids",
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

    # ------------------------------------------------------------
    # CRUD METHODS
    # ------------------------------------------------------------

    def copy(self, default=None):
        ctx = dict(self.env.context)
        ctx.pop("default_product_id", None)
        self = self.with_context(ctx)
        new_orders = super().copy(default=default)
        for line in new_orders.line_ids:
            if line.product_id:
                line.date_planned = line._get_date_planned(line.selected_seller_id)
        return new_orders

    # _unlink_except_draft_or_cancel is inherited from order.mixin (base_order).

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    def _get_confirmed_type_name(self):
        return _("Purchase Order")

    @api.depends("state", "date_order", "date_confirmed")
    def _compute_date_calendar_start(self):
        """
        Compute calendar start date for purchase order.

        Uses date_confirmed when order is confirmed (purchase state),
        otherwise uses date_order.

        :return: None (sets date_calendar_start field)
        """
        for order in self:
            order.date_calendar_start = (
                order.date_confirmed if order.state == "done" else order.date_order
            )

    def _get_validity_days(self):
        self.ensure_one()
        return self.company_id.po_quotation_validity_days

    def _get_default_user_from_partner(self):
        """Buyer from the partner, falling back to the current user."""
        self.ensure_one()
        return (
            self.partner_id.user_purchase_id
            or self.commercial_partner_id.user_purchase_id
            or (
                self.env.user.has_group("purchase.group_purchase_user")
                and self.env.user
            )
            or self.env["res.users"]
        )

    @api.depends("state", "partner_id", "partner_ref", "origin")
    def _compute_duplicated_order_ids(self):
        super()._compute_duplicated_order_ids()

    @api.depends("company_id", "partner_id")
    def _compute_currency_id(self):
        for order in self:
            order = order.with_company(order.company_id)
            order.currency_id = (
                order.partner_id.property_purchase_currency_id
                or order.company_id.currency_id
            )

    @api.depends(
        "company_id",
        "partner_id",
        "partner_id.receipt_reminder_email",
        "partner_id.reminder_date_before_receipt",
    )
    def _compute_receipt_reminder_email(self):
        for order in self:
            order.receipt_reminder_email = order.partner_id.with_company(
                order.company_id,
            ).receipt_reminder_email
            order.reminder_date_before_receipt = order.partner_id.with_company(
                order.company_id,
            ).reminder_date_before_receipt

    @api.depends("state", "line_ids", "line_ids.date_planned")
    def _compute_date_planned(self):
        """date_planned = the earliest date_planned across all order lines."""
        for order in self:
            if order.state == "cancel":
                order.date_planned = False
                continue

            dates_list = order.line_ids.filtered(
                lambda line: not line.display_type and line.date_planned,
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
                ("state", "=", "done"),
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

    @api.depends_context("show_total_amount")
    @api.depends("currency_id", "name", "partner_ref", "amount_total")
    def _compute_display_name(self):
        super()._compute_display_name()

    def _get_display_name_suffix(self):
        suffix = ""
        if self.partner_ref:
            suffix += " (" + self.partner_ref + ")"
        if self.env.context.get("show_total_amount") and self.amount_total:
            suffix += ": " + formatLang(
                self.env,
                self.amount_total,
                currency_obj=self.currency_id,
            )
        return suffix

    @api.depends(
        "partner_id.name",
        "partner_id.purchase_warn_msg",
        "partner_id.parent_id.name",
        "partner_id.parent_id.purchase_warn_msg",
        "line_ids.purchase_line_warn_msg",
        "line_ids.product_id.name",
    )
    def _compute_purchase_warning_text(self):
        if not self.env.user.has_group("purchase.group_warning_purchase"):
            self.purchase_warning_text = ""
            return
        for order in self:
            warnings = OrderedSet()
            if partner_msg := order.partner_id.purchase_warn_msg:
                warnings.add(
                    (order.partner_id.name or order.partner_id.display_name)
                    + " - "
                    + partner_msg,
                )
            if partner_parent_msg := order.partner_id.parent_id.purchase_warn_msg:
                parent = order.partner_id.parent_id
                warnings.add(
                    (parent.name or parent.display_name) + " - " + partner_parent_msg
                )
            for line in order.line_ids:
                if product_msg := line.purchase_line_warn_msg:
                    warnings.add(line.product_id.display_name + " - " + product_msg)
            order.purchase_warning_text = "\n".join(warnings)

    # ------------------------------------------------------------
    # SEARCH METHODS
    # ------------------------------------------------------------

    def _get_is_late_search_domain(self, domain, positive):
        """Late purchases also require a line not yet fully transferred."""
        lines_domain = Domain("order_id", "any", domain) & Domain.custom(
            to_sql=lambda model, alias, query: SQL(
                "%s < %s" if positive else "%s >= %s",
                model._field_to_sql(alias, "qty_transferred", query),
                model._field_to_sql(alias, "product_qty", query),
            ),
        )
        return Domain("line_ids", "any", lines_domain)

    # ------------------------------------------------------------
    # ONCHANGE METHODS
    # ------------------------------------------------------------

    def onchange(self, values, field_names, fields_spec):
        """
        Override onchange to NOT update all date_planned on PO lines when
        date_planned on PO is updated by the change of date_planned on PO lines.
        """
        result = super().onchange(values, field_names, fields_spec)
        if (
            any(self._must_delete_date_planned(field) for field in field_names)
            and "value" in result
        ):
            for line in result["value"].get("line_ids", []):
                if line[0] == Command.UPDATE and "date_planned" in line[2]:
                    del line[2]["date_planned"]
        return result

    @api.onchange("partner_id", "company_id")
    def onchange_partner_id(self):
        # Ensures all properties and fiscal positions
        # are taken with the company of the order
        # if not defined, with_company doesn't change anything.
        self = self.with_company(self.company_id)
        if not self.partner_id:
            self.fiscal_position_id = False
        else:
            self.fiscal_position_id = self.env[
                "account.fiscal.position"
            ]._get_fiscal_position(self.partner_id)
            self.payment_term_id = self.partner_id.property_supplier_payment_term_id.id
            if self.partner_id.user_purchase_id:
                self.user_id = self.partner_id.user_purchase_id
        return {}

    @api.onchange("date_planned")
    def _onchange_date_planned(self):
        if self.date_planned:
            self.line_ids.filtered(
                lambda line: not line.display_type,
            ).date_planned = self.date_planned

    @api.onchange("company_id", "fiscal_position_id")
    def _onchange_fiscal_position_id(self):
        """Trigger the recompute of the taxes if the fiscal position is changed"""
        self.line_ids._compute_tax_ids()

    # ------------------------------------------------------------
    # ACTION METHODS
    # ------------------------------------------------------------

    # action_acknowledge is inherited from order.mixin (base_order).

    def action_bill_matching(self):
        self.ensure_one()
        product_ids = self.line_ids.product_id.ids
        return {
            "name": _("Bill Matching"),
            "type": "ir.actions.act_window",
            "res_model": "purchase.bill.line.match",
            "views": [
                (self.env.ref("purchase.purchase_bill_line_match_list").id, "list"),
            ],
            "domain": [
                ("company_id", "in", self.env.company.ids),
                (
                    "partner_id",
                    "in",
                    (self.partner_id | self.partner_id.commercial_partner_id).ids,
                ),
                "|",
                ("purchase_order_id", "=", self.id),
                "&",
                ("purchase_order_id", "=", False),
                ("product_id", "in", product_ids),
            ],
        }

    # action_confirm is inherited from order.mixin (base_order); purchase only
    # customizes the post-confirmation hook below and _prepare_confirmation_values.

    def _action_confirm(self):
        """Implementation of additional mechanism of Purchase Order confirmation.

        This method should be extended when the confirmation should generate
        other documents. In this method, the PO are in 'done' state.
        """
        for order in self:
            order._create_supplier_to_product()

    def action_draft(self):
        # Consistent with sale.order.action_draft: only draft/cancelled orders
        # are resettable to draft. A confirmed order must be cancelled first, so
        # calling this on one (e.g. via a server action or a mixed selection) is
        # a graceful no-op rather than surfacing the low-level state-transition
        # guard (done -> draft is intentionally illegal; see
        # test_illegal_transition_done_to_draft_raises).
        self.filtered(lambda order: order.state in ("draft", "cancel")).write(
            {"state": "draft"},
        )

    def action_lock(self):
        """Lock purchase orders to prevent modifications."""
        self.write({"locked": True, "priority": "0"})

    # -------------------------------------------------------------------------
    # RFQ Merge: purchase-specific hooks into order.merge.mixin (base_order).
    # action_merge and the whole merge pipeline (eligibility, grouping, line
    # consolidation, metadata, messages, result action) live in the mixin; PO
    # only customises the wording and the finalize step below.
    # -------------------------------------------------------------------------

    def _merge_validate_selection(self, orders):
        # RFQ-specific wording (the mixin default says "orders").
        if len(orders) < 2:
            raise UserError(
                _("Please select at least two RFQs to merge."),
            )

    def _get_merge_group_description(self):
        # Criteria are those of _prepare_grouped_data below.
        return _("- Vendor\n- Currency\n- Dropship Address")

    def _get_merge_result_name(self):
        return _("Merged RFQs")

    def _merge_finalize(self, target, sources):
        # Cancel the sources (mixin) then wire up alternative-PO references.
        super()._merge_finalize(target, sources)
        target._merge_alternative_po(sources)

    def action_print_quotation(self):
        self.filtered(lambda order: order.state == "draft").write(
            {"printed_before": True},
        )
        return self.env.ref("purchase.report_purchase_quotation").report_action(self)

    def action_purchase_comparison(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "purchase.action_purchase_history",
        )
        action["display_name"] = _("Purchase Comparison for %s", self.display_name)
        action["domain"] = [("product_id", "in", self.line_ids.product_id.ids)]
        return action

    def action_send_rfq(self):
        """
        This function opens a window to compose an email, with the edi purchase template message loaded by default
        """
        self.ensure_one()
        ctx = dict(self.env.context or {})
        ctx.update(
            {
                "default_model": "purchase.order",
                "default_res_ids": self.ids,
                "default_composition_mode": "comment",
                "default_email_layout_xmlid": "mail.mail_notification_layout_with_responsible_signature",
                "email_notification_allow_footer": True,
                "force_email": True,
                "hide_mail_template_management_options": True,
                "mark_rfq_as_sent": True,
                "model_description": self.type_name,
            },
        )
        template_id = self._get_mail_template()
        if template_id:
            ctx.update({"default_template_id": template_id})
        # In the case of a RFQ or a PO, we want the "View..." button in line with the state of the
        # object. Therefore, we pass the model description in the context, in the language in which
        # the template is rendered.
        lang = self.env.context.get("lang")
        if {"default_template_id", "default_model", "default_res_id"} <= ctx.keys():
            template = self.env["mail.template"].browse(template_id)
            if template and template.lang:
                lang = template._render_lang([ctx["default_res_id"]])[
                    ctx["default_res_id"]
                ]
        self = self.with_context(lang=lang)
        compose_form_id = self._get_mail_compose_form()
        return {
            "name": _("Compose Email"),
            "type": "ir.actions.act_window",
            "res_model": "mail.compose.message",
            "view_mode": "form",
            "views": [(compose_form_id, "form")],
            "view_id": compose_form_id,
            "target": "new",
            "context": ctx,
        }

    def action_view_invoice(self, invoices=False):
        """This function returns an action that display existing vendor bills of
        given purchase order ids. When only one found, show the vendor bill
        immediately.
        """
        if not invoices:
            self.invalidate_model(["invoice_ids"])
            invoices = self.invoice_ids

        action = self.env["ir.actions.act_window"]._for_xml_id(
            "account.action_move_in_invoice_type",
        )

        if len(invoices) > 1:
            action["domain"] = [("id", "in", invoices.ids)]
        elif len(invoices) == 1:
            res = self.env.ref("account.view_move_form", False)
            form_view = [((res and res.id) or False, "form")]
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
                },
            )
        action["context"] = context
        return action

    # ------------------------------------------------------------
    # MAIL METHODS
    # ------------------------------------------------------------

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

    def _tweak_notify_recipient_groups(self, groups):
        # Tweak "view document" button for portal customers,
        # calling directly routes for confirm specific to PO model.
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
                access_opt.update(
                    title=_("View %s", self.type_name),
                    url=self.get_base_url() + self.get_confirm_url(),
                )

    def _get_mail_subtitles(self, render_context):
        subtitles = [render_context["record"].name]
        # don't show price on RFQ mail
        if self.state == "draft":
            subtitles.append(
                _(
                    "Order\N{NO-BREAK SPACE}due\N{NO-BREAK SPACE}%(date)s",
                    date=format_date(
                        self.env,
                        self.date_order,
                        lang_code=render_context.get("lang"),
                    ),
                ),
            )
        else:
            subtitles.append(
                format_amount(
                    self.env,
                    self.amount_total,
                    self.currency_id,
                    lang_code=render_context.get("lang"),
                ),
            )
        return subtitles

    def _get_state_track_subtype_xmlid(self, init_values):
        if "state" in init_values and self.state == "done":
            return "purchase.mt_rfq_confirmed"

        elif "locked" in init_values and self.locked:
            return "purchase.mt_rfq_done"

        elif "sent" in init_values and self.sent:
            return "purchase.mt_rfq_sent"

        return None

    def _update_update_date_activity(self, updated_dates, activity):
        for line, date in updated_dates:
            activity.note += Markup("<p> - %s</p>\n") % _(
                "%(product)s from %(original_receipt_date)s to %(new_receipt_date)s",
                product=line.product_id.display_name,
                original_receipt_date=line.date_planned.date(),
                new_receipt_date=date.date(),
            )

    # ------------------------------------------------------------
    # CATALOGUE MIXIN METHODS
    # ------------------------------------------------------------

    def action_add_from_catalog(self):
        res = super().action_add_from_catalog()
        kanban_view_id = self.env.ref(
            "purchase.view_product_product_kanban_catalog_purchase_only",
        ).id
        res["views"][0] = (kanban_view_id, "kanban")
        res["search_view_id"] = [
            self.env.ref("purchase.view_product_product_search_catalog").id,
            "search",
        ]
        res["context"]["partner_id"] = self.partner_id.id
        return res

    def _get_action_add_from_catalog_extra_context(self):
        return {
            **super()._get_action_add_from_catalog_extra_context(),
            "precision": self.env["decimal.precision"].precision_get("Product Unit"),
            "product_catalog_currency_id": self.currency_id.id,
            "product_catalog_digits": self.line_ids._fields["price_unit"].get_digits(
                self.env,
            ),
            "search_default_seller_ids": self.partner_id.name,
            "show_sections": bool(self.id),
        }

    def _get_product_catalog_order_data(self, products, **kwargs):
        res = super()._get_product_catalog_order_data(products, **kwargs)
        for product in products:
            res[product.id] |= self._get_product_price_and_data(product)
        return res

    def _get_catalog_editable_states(self):
        return {"draft", "sent"}

    def _get_catalog_removed_line_price(self, product, **kwargs):
        return self._get_product_price_and_data(product)["price"]

    def _catalog_on_line_created(self, line, **kwargs):
        line = super()._catalog_on_line_created(line, **kwargs)
        if line.selected_seller_id:
            # Fix the PO line's price on the seller's one.
            seller = line.selected_seller_id
            price = seller.price
            if seller.currency_id != self.currency_id:
                price = seller.currency_id._convert(price, self.currency_id)
            line.price_unit = line.price_unit_auto = price
            line.discount = seller.discount
        return line

    def _get_catalog_line_price(self, line):
        return line.price_unit_discounted_taxexc

    # ------------------------------------------------------------
    # PRODUCT DOCUMENTS METHODS
    # ------------------------------------------------------------

    def _get_import_template_label(self):
        return _("Import Template for Requests for Quotation")

    def _get_import_template_path(self):
        return "/purchase/static/xls/requests_for_quotation_import_template.xlsx"

    # ------------------------------------------------------------
    # EDI METHODS
    # ------------------------------------------------------------

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    def _create_downpayments(self, line_vals):
        self.ensure_one()

        # create section
        if not any(line.display_type and line.is_downpayment for line in self.line_ids):
            section_line = self.line_ids.create(
                self._prepare_down_payment_line_section_values(),
            )
        else:
            section_line = self.line_ids.filtered(
                lambda line: line.display_type and line.is_downpayment,
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

    def _get_invoiceable_lines(self, final=False):
        """Bills cover every line; sections are filtered while building."""
        self.ensure_one()
        return self.line_ids

    def _prepare_invoice_line_commands(self, invoiceable_lines, sequence=10):
        """Keep only the sections directly followed by a product line."""
        commands = []
        pending_section = None
        for line in invoiceable_lines:
            if line.display_type in ("line_section", "line_subsection"):
                pending_section = line
                continue
            if pending_section:
                line_vals = pending_section._prepare_aml_vals()
                line_vals.update({"sequence": sequence})
                commands.append(Command.create(line_vals))
                sequence += 1
                pending_section = None
            line_vals = line._prepare_aml_vals()
            line_vals.update({"sequence": sequence})
            commands.append(Command.create(line_vals))
            sequence += 1
        return commands, sequence

    def _get_invoice_grouping_keys(self):
        return ["company_id", "partner_id", "currency_id"]

    def _create_invoice_moves(self, invoice_vals_list):
        """Plain per-company create (no sudo): billing needs account rights."""
        invoices = self.env["account.move"]
        AccountMove = self.env["account.move"].with_context(
            default_move_type=self._get_invoice_move_types()[0],
        )
        for vals in invoice_vals_list:
            invoices |= AccountMove.with_company(vals["company_id"]).create(vals)
        return invoices

    def create_invoice(self, attachment_ids=False):
        """Create the invoice associated to the PO."""
        invoices = self._create_invoices()

        # Link the attachments to the invoice
        if attachment_ids:
            attachments = self.env["ir.attachment"].browse(attachment_ids)
            if attachments:
                if len(invoices) != 1:
                    raise ValidationError(
                        _("You can only upload a bill for a single vendor at a time."),
                    )
                invoices.with_context(
                    skip_is_manually_modified=True
                )._extend_with_attachments(
                    invoices._to_files_data(attachments),
                    new=True,
                )
                invoices.message_post(attachment_ids=attachments.ids)
                attachments.write({"res_model": "account.move", "res_id": invoices.id})

        return invoices

    def action_create_invoice_from_file(self, attachment_ids=False):
        """Create a vendor bill from uploaded files and return navigation action.

        Wrapper around :meth:`create_invoice` intended for the JS file uploader
        widget, which needs an ``ir.actions.act_window`` dict to navigate to
        the newly created bill. Python callers should use :meth:`create_invoice`
        directly and work with the returned recordset.

        :param attachment_ids: Optional list of ``ir.attachment`` IDs to link.
        :returns: Window action opening the created vendor bill.
        """
        invoices = self.create_invoice(attachment_ids=attachment_ids)
        return self.action_view_invoice(invoices)

    def _create_supplier_to_product(self):
        """Add the partner to the supplier list of products on this order.

        Creates supplier info records for products where the order's partner
        is not yet registered as a seller, up to MAX_SUPPLIERS_PER_PRODUCT.

        Performance: collects all new supplier info vals first, then creates
        them in a single batch call instead of writing one-by-one per line.
        """
        # Do not add a contact as a supplier
        partner = (
            self.partner_id
            if not self.partner_id.parent_id
            else self.partner_id.parent_id
        )
        partners = partner | self.partner_id

        suppinfo_vals_list = []
        seen_tmpls = set()

        for line in self.line_ids:
            if not line.product_id:
                continue
            tmpl = line.product_id.product_tmpl_id
            # Only add one supplierinfo per product template per order
            if tmpl.id in seen_tmpls:
                continue
            already_seller = partners & line.product_id.seller_ids.mapped("partner_id")
            if (
                already_seller
                or len(line.product_id.seller_ids) > const.MAX_SUPPLIERS_PER_PRODUCT
            ):
                seen_tmpls.add(tmpl.id)
                continue

            seen_tmpls.add(tmpl.id)
            price = line.price_unit
            # Compute the price for the template's UoM, because the supplier's UoM is related to that UoM.
            if tmpl.uom_id != line.product_uom_id:
                price = line.product_uom_id._compute_price(price, tmpl.uom_id)

            supplierinfo = self._prepare_supplierinfo(
                partner,
                line,
                price,
                line.currency_id,
            )
            # In case the order partner is a contact address, a new supplierinfo is created on
            # the parent company. In this case, we keep the product name and code.
            if line.selected_seller_id:
                supplierinfo["product_name"] = line.selected_seller_id.product_name
                supplierinfo["product_code"] = line.selected_seller_id.product_code
                supplierinfo["product_uom_id"] = line.product_uom_id.id
            supplierinfo["product_tmpl_id"] = tmpl.id
            suppinfo_vals_list.append(supplierinfo)

        # Supplier info should be added regardless of the user access rights
        if suppinfo_vals_list:
            self.env["product.supplierinfo"].sudo().create(suppinfo_vals_list)

    def get_acknowledge_url(self):
        return self.get_portal_url(query_string="&acknowledge=True")

    def get_confirm_url(self, confirm_type=None):
        """Create url for confirm reminder or purchase reception email for sending
        in mail. Unsuported anymore. We only use the acknowledge mechanism. Keep it
        for backward compatibility"""
        if confirm_type in ["reminder", "reception", "decline"]:
            return self.get_acknowledge_url()
        return self.get_portal_url()

    def _get_default_create_section_values(self):
        """Return the default values for creating a section line in the purchase order through
        catalog.

        :return: A dictionary with default values for creating a new section.
        :rtype: dict
        """
        return {"product_qty": 0}

    def get_localized_date_planned(self, date_planned=False):
        """Returns the localized date planned in the timezone of the order's user or the
        company's partner or UTC if none of them are set."""
        self.ensure_one()
        date_planned = date_planned or self.date_planned
        if not date_planned:
            return False

        if isinstance(date_planned, str):
            date_planned = fields.Datetime.from_string(date_planned)
        tz = self.get_timezone()
        return date_planned.astimezone(tz)

    def _get_mail_template(self):
        ir_model_data = self.env["ir.model.data"]
        try:
            if self.env.context.get("send_rfq", False):
                template_id = ir_model_data._xmlid_lookup(
                    "purchase.email_template_edi_purchase",
                )[1]
            else:
                template_id = ir_model_data._xmlid_lookup(
                    "purchase.email_template_edi_purchase_done",
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
                ("state", "=", "done"),
                ("acknowledged", "=", False),
                ("receipt_reminder_email", "=", True),
            ],
        ).filtered(
            lambda p: (
                p.mapped("line_ids.product_id.product_tmpl_id.type") != ["service"]
            ),
        )

    def _get_product_price_and_data(self, product):
        """Fetch the product's data used by the purchase's catalog.

        :return: the product's price and, if applicable, the minimum quantity to
                 buy and the product's packaging data.
        :rtype: dict
        """
        self.ensure_one()
        product_infos = {
            "price": product.standard_price,
            "uomDisplayName": product.uom_id.display_name,
        }
        params = {"order_id": self}
        # Check if there is a price and a minimum quantity for the order's vendor.
        seller = product._select_seller(
            partner_id=self.partner_id,
            quantity=None,
            date=fields.Date.context_today(self, timestamp=self.date_order),
            uom_id=product.uom_id,
            ordered_by="min_qty",
            params=params,
        )
        if seller:
            product_uom_id = (seller.product_id or seller.product_tmpl_id).uom_id
            price = seller.price_discounted
            if seller.currency_id != self.currency_id:
                price = seller.currency_id._convert(price, self.currency_id)
            if seller.product_uom_id != product_uom_id:
                # The discounted price is expressed in the product's UoM, not in the vendor
                # price's UoM, so we need to convert it into to match the displayed UoM.
                price = product_uom_id._compute_price(price, seller.product_uom_id)
                product_infos.update(
                    uomFactor=seller.product_uom_id.factor / product_uom_id.factor
                )
            product_infos.update(
                price=price,
                min_qty=seller.min_qty,
                uomDisplayName=seller.product_uom_id.display_name,
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
        update_param = urlencode({"update": "True"})
        return self.get_portal_url(query_string="&%s" % update_param)

    def _merge_alternative_po(self, rfqs):
        pass

    @api.model
    def prepare_dashboard(self):
        """This function returns the values to populate the custom dashboard in
        the purchase order views.
        """
        if not self.env.user._is_internal():
            raise AccessDenied

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
            rfq_draft_domain,
            groupby,
            aggregate,
        )
        _update("draft", result, rfq_draft_group)

        rfq_sent_domain = [("sent", "=", True), ("state", "=", "draft")]
        rfq_sent_group = self.env["purchase.order"]._read_group(
            rfq_sent_domain,
            groupby,
            aggregate,
        )
        _update("sent", result, rfq_sent_group)

        rfq_late_domain = [
            ("state", "=", "draft"),
            ("date_order", "<", fields.Datetime.now()),
        ]
        rfq_late_group = self.env["purchase.order"]._read_group(
            rfq_late_domain,
            groupby,
            aggregate,
        )
        _update("late", result, rfq_late_group)

        rfq_not_acknowledge = [("state", "=", "done"), ("acknowledged", "=", False)]
        rfq_not_acknowledge_group = self.env["purchase.order"]._read_group(
            rfq_not_acknowledge,
            groupby,
            aggregate,
        )
        _update("not_acknowledged", result, rfq_not_acknowledge_group)

        rfq_late_receipt = [("state", "=", "done"), ("is_late", "=", True)]
        rfq_late_receipt_group = self.env["purchase.order"]._read_group(
            rfq_late_receipt,
            groupby,
            aggregate,
        )
        _update("late_receipt", result, rfq_late_receipt_group)

        three_months_ago = fields.Datetime.to_string(
            fields.Datetime.now() - relativedelta(months=3),
        )

        # Use SQL aggregation instead of Python loop for better performance
        # This computes averages in a single query instead of iterating all POs
        self.env.cr.execute(
            """
            SELECT
                AVG(EXTRACT(EPOCH FROM (date_confirmed - create_date))) AS avg_global_seconds,
                AVG(CASE WHEN user_id = %s
                    THEN EXTRACT(EPOCH FROM (date_confirmed - create_date))
                    END) AS avg_my_seconds
            FROM purchase_order
            WHERE state = 'done'
              AND create_date >= %s
              AND date_confirmed IS NOT NULL
            """,
            [self.env.user.id, three_months_ago],
        )
        row = self.env.cr.fetchone()
        avg_global_deliveries_seconds = row[0] or 0
        avg_my_deliveries_seconds = row[1] or 0

        result["global"]["days_to_order"] = float_repr(
            avg_global_deliveries_seconds / 60 / 60 / 24,
            precision_digits=2,
        )
        result["my"]["days_to_order"] = float_repr(
            avg_my_deliveries_seconds / 60 / 60 / 24,
            precision_digits=2,
        )

        return result

    def _prepare_confirmation_values(self):
        """Prepare the purchase order confirmation values.

        Note: self can contain multiple records.

        :return: Purchase Order confirmation values
        :rtype: dict
        """
        return {"state": "done", "date_confirmed": fields.Datetime.now()}

    def _prepare_down_payment_line_section_values(self):
        """Prepare the values to create a section line for the down payment on the current PO.

        :return: A dictionary to create a new PO section line.
        """
        values = super()._prepare_down_payment_line_section_values()
        values.update(
            sequence=(self.line_ids[-1:].sequence or 9) + 1,
            name=_("Down Payments"),
        )
        return values

    def _prepare_grouped_data(self, rfq):
        return (rfq.partner_id.id, rfq.currency_id.id, rfq.dest_address_id.id)

    def _prepare_invoice_vals(self):
        """Prepare the dict of values to create the new invoice for a purchase order."""
        values = super()._prepare_invoice_vals()
        partner_bank_id = self.commercial_partner_id.bank_ids.filtered_domain(
            [("company_id", "in", (False, self.company_id.id))],
        )[:1]
        values["partner_bank_id"] = partner_bank_id.id
        return values

    def _prepare_supplierinfo(self, partner, line, price, currency):
        # Prepare supplierinfo data when adding a product
        return {
            "partner_id": partner.id,
            "sequence": (
                max(line.product_id.seller_ids.mapped("sequence")) + 1
                if line.product_id.seller_ids
                else 1
            ),
            "min_qty": 1.0,
            "price": price,
            "currency_id": currency.id,
            "discount": line.discount,
            "delay": 0,
        }

    def _send_reminder_mail(self, send_single=False):
        if not self.env.user.has_group("purchase.group_send_reminder"):
            return None

        template = self.env.ref(
            "purchase.email_template_edi_purchase_reminder",
            raise_if_not_found=False,
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
        return None

    def _send_reminder_open_composer(self, template_id):
        self.ensure_one()
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
                "model_description": self.type_name,
            },
        )
        lang = self.env.context.get("lang")
        if {"default_template_id", "default_model", "default_res_id"} <= ctx.keys():
            template = self.env["mail.template"].browse(template_id)
            if template and template.lang:
                lang = template._render_lang([ctx["default_res_id"]])[
                    ctx["default_res_id"]
                ]
        self = self.with_context(lang=lang)
        compose_form_id = self._get_mail_compose_form()
        return {
            "name": _("Compose Email"),
            "type": "ir.actions.act_window",
            "res_model": "mail.compose.message",
            "view_mode": "form",
            "views": [(compose_form_id, "form")],
            "view_id": compose_form_id,
            "target": "new",
            "context": ctx,
        }

    def send_reminder_preview(self):
        self.ensure_one()
        if not self.env.user.has_group("purchase.group_send_reminder"):
            return None

        template = self.env.ref(
            "purchase.email_template_edi_purchase_reminder",
            raise_if_not_found=False,
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
                    _("A sample email has been sent to %s.", self.env.user.email),
                ),
            }
        return None

    def _update_order_lines_date_planned(self, updated_dates):
        # create or update the activity
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

        # update the date on PO line
        for line, date in updated_dates:
            line._update_date_planned(date)

    # ------------------------------------------------------------
    # VALIDATIONS
    # ------------------------------------------------------------

    # _can_confirm_proper_state, _can_confirm_has_lines and
    # _can_confirm_lines_have_product are inherited from order.mixin
    # (base_order); purchase only implements the analytic-distribution check.

    def _can_confirm_analytic_distribution(self):
        """Ensure all order lines have valid analytic distributions.

        Analytic distributions must be validated before confirming the order
        to prevent creating confirmed orders with invalid accounting data.
        This validation is triggered when context key 'validate_analytic' is True.

        For each order with invalid analytics, collects the line numbers and
        specific validation errors to help users fix the issues.
        """
        if not self.env.context.get("validate_analytic"):
            return

        orders_with_errors = {}

        for order in self:
            line_errors = []
            for line in order.line_ids:
                if line.display_type:
                    continue
                try:
                    line._validate_distribution(
                        product=line.product_id.id,
                        business_domain="purchase_order",
                        company_id=line.company_id.id,
                    )
                except (UserError, ValidationError) as e:
                    line_errors.append(
                        _(
                            "  • Line %(line_num)s (%(product)s): %(error)s",
                            line_num=line.sequence or "?",
                            product=line.product_id.display_name or _("No product"),
                            error=str(e).split("\n")[0],  # First line of error message
                        ),
                    )

            if line_errors:
                orders_with_errors[order] = line_errors

        if orders_with_errors:
            error_details = []
            for order, line_errors in orders_with_errors.items():
                error_details.append(
                    _(
                        "%(order)s:\n%(lines)s",
                        order=order.display_name,
                        lines="\n".join(line_errors),
                    ),
                )

            raise UserError(
                _(
                    "Cannot confirm purchase orders with invalid analytic distributions:\n\n%s\n\n"
                    "Please fix the analytic distribution on the highlighted lines.",
                    "\n\n".join(error_details),
                ),
            )

    def _get_can_cancel_validation_methods(self):
        """Extend the base cancel validators with the posted-bill guard.

        ``_can_cancel_check_state`` and ``_can_cancel_except_locked`` come from
        order.mixin (base_order); purchase adds ``_can_cancel_except_invoiced``.
        """
        return [
            *super()._get_can_cancel_validation_methods(),
            "_can_cancel_except_invoiced",
        ]

    def _can_cancel_except_invoiced(self):
        """Ensure orders don't have posted vendor bills.

        Purchase orders with posted bills cannot be cancelled as this would
        create accounting inconsistencies. Bills must be cancelled first.

        Performance note: Uses filtered() to avoid loading all invoice records.
        """
        # Optimized: Use filtered instead of any() to leverage ORM
        orders_with_posted_invoices = self.filtered(
            lambda order: order.invoice_ids.filtered(lambda inv: inv.state == "posted"),
        )

        if orders_with_posted_invoices:
            # Build detailed error message with order and invoice info
            error_details = []
            for order in orders_with_posted_invoices:
                posted_bills = order.invoice_ids.filtered(lambda i: i.state == "posted")
                bill_names = ", ".join(posted_bills.mapped("name"))
                error_details.append(
                    _(
                        "• %(order)s has posted bills: %(bills)s",
                        order=order.display_name,
                        bills=bill_names,
                    ),
                )

            raise UserError(
                _(
                    "Cannot cancel purchase orders with posted vendor bills:\n\n%s\n\n"
                    "Please cancel or reset the bills to draft first.",
                    "\n".join(error_details),
                ),
            )

    def _must_delete_date_planned(self, field_name):
        # To be overridden
        return field_name == "line_ids"

    # _should_be_locked is inherited from order.mixin (base_order): it resolves
    # company.order_lock_po and the purchase.group_auto_done_setting group
    # generically via _get_lock_setting_field / _get_order_type.
