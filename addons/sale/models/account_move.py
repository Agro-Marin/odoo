from odoo import _, api, fields, models
from odoo.tools import OrderedSet, groupby


class AccountMove(models.Model):
    _name = "account.move"
    _inherit = ["account.move", "utm.mixin"]

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    # UTMs - enforcing the fact that we want to 'set null' when relation is unlinked
    campaign_id = fields.Many2one(ondelete="set null")
    medium_id = fields.Many2one(ondelete="set null")
    source_id = fields.Many2one(ondelete="set null")

    team_id = fields.Many2one(
        comodel_name="crm.team",
        string="Sales Team",
        compute="_compute_team_id",
        store=True,
        readonly=False,
        domain="[('company_id', 'in', [False, company_id])]",
        ondelete="set null",
        tracking=True,
    )
    sale_order_count = fields.Integer(
        string="Sale Order Count",
        compute="_compute_origin_so_count",
        compute_sudo=True,
    )
    sale_warning_text = fields.Text(
        string="Sale Warning",
        compute="_compute_sale_warning_text",
        help="Internal warning for the partner or the products as set by the user.",
    )

    # ------------------------------------------------------------
    # CRUD METHODS
    # ------------------------------------------------------------

    def unlink(self):
        downpayment_lines = self.mapped("line_ids.sale_line_ids").filtered(
            lambda line: (
                line.is_downpayment and line.invoice_line_ids <= self.mapped("line_ids")
            ),
        )
        res = super().unlink()
        if downpayment_lines:
            downpayment_lines.unlink()
        return res

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    @api.depends("move_type", "partner_id")
    def _compute_invoice_default_user(self):
        """Extend to set salesperson for customer invoices.

        For sale documents, sets the salesperson from the partner's default
        salesperson or the commercial partner's salesperson.
        """
        super()._compute_invoice_default_user()
        for move in self:
            if move.is_sale_document(include_receipts=True):
                if not move.invoice_user_id or move.invoice_user_id == self.env.user:
                    move.invoice_user_id = (
                        move.partner_id.user_id
                        or move.partner_id.commercial_partner_id.user_id
                        or self.env.user
                    )

    @api.depends("invoice_user_id")
    def _compute_team_id(self):
        sale_moves = self.filtered(
            lambda move: move.is_sale_document(include_receipts=True),
        )
        for (user_id, company_id), moves in groupby(
            sale_moves,
            key=lambda m: (m.invoice_user_id.id, m.company_id.id),
        ):
            self.env["account.move"].concat(*moves).team_id = (
                self.env["crm.team"]
                .with_context(
                    allowed_company_ids=[company_id],
                )
                ._get_default_team_id(
                    user_id=user_id,
                )
            )

    @api.depends("line_ids.sale_line_ids")
    def _compute_origin_so_count(self):
        for move in self:
            move.sale_order_count = len(move.line_ids.sale_line_ids.order_id)

    @api.depends(
        "partner_id.name",
        "partner_id.sale_warn_msg",
        "invoice_line_ids.product_id.sale_line_warn_msg",
        "invoice_line_ids.product_id.display_name",
    )
    def _compute_sale_warning_text(self):
        if not self.env.user.has_group("sale.group_warning_sale"):
            self.sale_warning_text = ""
            return
        for move in self:
            if move.move_type != "out_invoice":
                move.sale_warning_text = ""
                continue
            warnings = OrderedSet()
            if partner_msg := move.partner_id.sale_warn_msg:
                warnings.add(
                    (move.partner_id.name or move.partner_id.display_name)
                    + " - "
                    + partner_msg,
                )
            if partner_parent_msg := move.partner_id.parent_id.sale_warn_msg:
                parent = move.partner_id.parent_id
                warnings.add(
                    (parent.name or parent.display_name) + " - " + partner_parent_msg
                )
            for product in move.invoice_line_ids.product_id:
                if product_msg := product.sale_line_warn_msg:
                    warnings.add(product.display_name + " - " + product_msg)
            move.sale_warning_text = "\n".join(warnings)

    # ------------------------------------------------------------
    # ACTION METHODS
    # ------------------------------------------------------------

    def action_cancel(self):
        res = super().action_cancel()
        self.line_ids.filtered("is_downpayment").sale_line_ids.filtered(
            lambda line: not line.display_type,
        )._compute_name()
        return res

    def action_draft(self):
        res = super().action_draft()

        self.line_ids.filtered("is_downpayment").sale_line_ids.filtered(
            lambda line: not line.display_type,
        )._compute_name()

        return res

    def _action_invoice_ready_to_be_sent(self):
        """Trigger the send-invoice cron when an invoice becomes ready to be sent by mail."""
        res = super()._action_invoice_ready_to_be_sent()

        send_invoice_cron = self.env.ref(
            "sale.send_invoice_cron",
            raise_if_not_found=False,
        )
        if send_invoice_cron:
            send_invoice_cron._trigger()

        return res

    def action_post(self):
        """Validate the tax and unit price of downpayment lines after posting."""
        res = super().action_post()

        # We cannot change lines content on locked SO, changes on invoices are not forwarded to the SO if the SO is locked
        dp_lines = self.line_ids.sale_line_ids.filtered(
            lambda line: line.is_downpayment and not line.display_type,
        )
        dp_lines._compute_name()  # Update the description of DP lines (Draft -> Posted)
        downpayment_lines = dp_lines.filtered(lambda line: not line.order_id.locked)
        other_so_lines = downpayment_lines.order_id.line_ids - downpayment_lines
        real_invoices = set(other_so_lines.invoice_line_ids.move_id)
        for so_dpl in downpayment_lines:
            so_dpl.price_unit = so_dpl._get_downpayment_price_unit(real_invoices)
            so_dpl.tax_ids = so_dpl.invoice_line_ids.tax_ids

        return res

    def action_view_source_sale_orders(self):
        self.ensure_one()
        source_orders = self.line_ids.sale_line_ids.order_id
        result = self.env["ir.actions.act_window"]._for_xml_id("sale.action_sale_order")
        if len(source_orders) > 1:
            result["domain"] = [("id", "in", source_orders.ids)]
        elif len(source_orders) == 1:
            result["views"] = [
                (self.env.ref("sale.view_sale_order_form", False).id, "form")
            ]
            result["res_id"] = source_orders.id
        else:
            result = {"type": "ir.actions.act_window_close"}
        return result

    def _post(self, soft=True):
        """Auto-reconcile posted invoices with payments coming from in-process transactions.

        Useful when a sale order was marked "paid" via a payment transaction and is invoiced later.
        """
        posted = super()._post(soft)

        for invoice in posted.filtered(lambda move: move.is_invoice()):
            payments = invoice.mapped("transaction_ids.payment_id").filtered(
                lambda x: x.state == "in_process",
            )
            move_lines = payments.move_id.line_ids.filtered(
                lambda line: (
                    line.account_type in ("asset_receivable", "liability_payable")
                    and not line.reconciled
                ),
            )
            for line in move_lines:
                invoice.js_assign_outstanding_line(line.id)
        return posted

    def _reverse_moves(self, default_values_list=None, cancel=False):
        """Preserve UTM fields (campaign, medium, source) on the reversal entries."""
        if not default_values_list:
            default_values_list = [{} for move in self]
        # Don't mutate the caller's dicts in place: build a fresh list so a
        # caller reusing its default_values_list doesn't inherit UTM fields.
        default_values_list = [
            {
                **default_values,
                "campaign_id": move.campaign_id.id,
                "medium_id": move.medium_id.id,
                "source_id": move.source_id.id,
            }
            for move, default_values in zip(self, default_values_list, strict=True)
        ]
        return super()._reverse_moves(
            default_values_list=default_values_list,
            cancel=cancel,
        )

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    def _invoice_paid_hook(self):
        """Post a chatter note on the linked sales order(s) when an invoice is paid."""
        res = super()._invoice_paid_hook()
        todo = set()
        for invoice in self.filtered(lambda move: move.is_invoice()):
            for line in invoice.invoice_line_ids:
                for sale_line in line.sale_line_ids:
                    todo.add((sale_line.order_id, invoice.name))
        for order, name in todo:
            order.message_post(body=_("Invoice %s paid", name))
        return res

    def _get_sale_order_invoiced_amount(self, order):
        """
        Consider all lines on any invoice in self that stem from the sales order `order`. (All those invoices belong to order.company_id)
        This function returns the sum of the totals of all those lines.
        Note that this amount may be bigger than `order.amount_total`.
        """
        order_amount = 0
        for invoice in self:
            prices = sum(
                invoice.line_ids.filtered(
                    lambda x: (
                        x.display_type not in ("line_note", "line_section")
                        and order in x.sale_line_ids.order_id
                    ),
                ).mapped("price_total"),
            )
            order_amount += invoice.currency_id._convert(
                prices * -invoice.direction_sign,
                order.currency_id,
                invoice.company_id,
                # Draft invoices have no accounting ``date`` yet; fall back to
                # the document date so the FX rate matches the eventual posting.
                invoice.invoice_date or invoice.date or fields.Date.context_today(self),
            )
        return order_amount

    def _get_partner_credit_warning_exclude_amount(self):
        """Subtract the SO-originated portion of an invoice from the partner credit warning amount."""
        # On a draft invoice created from a sales order, after confirming the invoice the (partial)
        # amount stemming from sales orders will be subtracted from `credit_to_invoice`, reducing the
        # partner's total credit. The computation here mirrors that change of `credit_to_invoice`
        # (see `_compute_credit_to_invoice` and `_compute_amount_to_invoice` on `sale.order`).
        exclude_amount = super()._get_partner_credit_warning_exclude_amount()
        for order in self.line_ids.sale_line_ids.order_id:
            order_amount = min(
                self._get_sale_order_invoiced_amount(order),
                order.amount_taxinc_to_invoice,
            )
            order_amount_company = order.currency_id._convert(
                max(order_amount, 0),
                self.company_id.currency_id,
                self.company_id,
                fields.Date.context_today(self),
            )
            exclude_amount += order_amount_company
        return exclude_amount

    # ------------------------------------------------------------
    # VALIDATIONS
    # ------------------------------------------------------------

    def _is_downpayment(self):
        """True when every line of the move originates from a sale order downpayment line."""
        self.ensure_one()
        return (
            self.line_ids.sale_line_ids
            and all(
                sale_line.is_downpayment for sale_line in self.line_ids.sale_line_ids
            )
        ) or False
