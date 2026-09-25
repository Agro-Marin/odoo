from odoo import api, fields, models
from odoo.libs.debug_log import DebugLog
from odoo.tools import frozendict

_debug = DebugLog(__name__)


class AccountMove(models.Model):
    _name = "account.move"
    _inherit = ["account.move", "mixin.utm"]
    _access_anchors = frozendict(
        {
            "owner": models.Anchor("invoice_user_id", shared=True),
        }
    )

    campaign_id = fields.Many2one(ondelete="set null")
    medium_id = fields.Many2one(ondelete="set null")
    source_id = fields.Many2one(ondelete="set null")

    sale_order_count = fields.Integer(
        compute="_compute_sale_order_count",
        compute_sudo=True,
    )
    sale_warning_text = fields.Text(
        string="Sale Warning",
        compute="_compute_sale_warning_text",
        depends_context=("uid",),
        help="Internal warning for the partner or the products as set by the user.",
    )
    sale_customer_invoice_id = fields.Many2one(
        comodel_name="sale.invoice.match",
        string="Sales Auto-complete",
        store=False,
        readonly=False,
        help="Auto-complete from a previous invoice, credit note, or sales order.",
    )
    sale_id = fields.Many2one(
        comodel_name="sale.order",
        string="Sales Order",
        store=False,
        readonly=False,
        help="Auto-complete from a past sales order.",
    )
    sale_order_name = fields.Char(compute="_compute_sale_order_name")
    is_sale_matched = fields.Boolean(
        compute="_compute_is_sale_matched",
        help="0: SO not required or partially linked. 1: All lines linked",
    )

    def unlink(self):
        own_lines = self.line_ids
        downpayment_lines = own_lines.sale_line_ids.filtered(
            lambda line: line.is_downpayment and line.invoice_line_ids <= own_lines,
        )
        res = super().unlink()
        if downpayment_lines:
            _debug.lifecycle("downpayment_lines_unlinked", lines=downpayment_lines)
            downpayment_lines.unlink()
        return res

    @api.depends("move_type", "partner_id")
    def _compute_invoice_user_id(self):
        super()._compute_invoice_user_id()
        for move in self:
            if move.is_sale_document(include_receipts=True):
                if not move.invoice_user_id or move.invoice_user_id == self.env.user:
                    move.invoice_user_id = (
                        move.partner_id.user_id
                        or move.partner_id.commercial_partner_id.user_id
                        or self.env.user
                    )

    @api.depends("line_ids.sale_line_ids")
    def _compute_sale_order_count(self):
        for move in self:
            move.sale_order_count = len(move._get_source_orders("sale.order"))

    @api.depends("line_ids.sale_line_ids")
    def _compute_is_sale_matched(self):
        for move in self:
            move.is_sale_matched = move._is_matched_to_orders("sale.order")

    @api.depends(
        "sale_order_count",
        "invoice_line_ids.sale_line_ids.order_id.display_name",
    )
    def _compute_sale_order_name(self):
        for move in self:
            move.sale_order_name = move._get_source_order_name("sale.order")

    @api.onchange("sale_customer_invoice_id", "sale_id")
    def _onchange_sale_auto_complete(self):
        self._auto_complete_from_order("sale_customer_invoice_id", "sale_id")

    def action_sale_matching(self):
        return self._action_order_line_matching(
            self.env._("Sale Matching"),
            "sale.invoice.line.match",
            "sale.sale_invoice_line_match_list",
        )

    @api.depends(
        "partner_id.name",
        "partner_id.sale_warn_msg",
        "partner_id.parent_id.name",
        "partner_id.parent_id.sale_warn_msg",
        "invoice_line_ids.product_id.sale_line_warn_msg",
        "invoice_line_ids.product_id.display_name",
    )
    def _compute_sale_warning_text(self):
        if not self.env.user.has_group("sale.group_warning_sale"):
            self.sale_warning_text = ""
            _debug.logic("sale_warnings_skipped", reason="no_warning_group")
            return
        for move in self:
            move.sale_warning_text = move._get_order_warning_text(
                "out_invoice", "sale_warn_msg", "sale_line_warn_msg"
            )

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
        res = super()._action_invoice_ready_to_be_sent()

        send_invoice_cron = self.env.ref(
            "sale.send_invoice_cron",
            raise_if_not_found=False,
        )
        if send_invoice_cron:
            _debug.lifecycle("invoice_send_cron_triggered", moves=self)
            send_invoice_cron._trigger()

        return res

    def action_post(self):
        res = super().action_post()

        dp_lines = self.line_ids.sale_line_ids.filtered(
            lambda line: line.is_downpayment and not line.display_type,
        )
        dp_lines._compute_name()
        downpayment_lines = dp_lines.filtered(lambda line: not line.order_id.locked)
        other_so_lines = downpayment_lines.order_id.line_ids - downpayment_lines
        real_invoices = set(other_so_lines.invoice_line_ids.move_id)
        _debug.pipeline(
            "downpayment_lines_repriced",
            moves=self,
            lines=downpayment_lines,
            real_invoices=len(real_invoices),
        )
        for so_dpl in downpayment_lines:
            so_dpl.price_unit = so_dpl._get_downpayment_price_unit(real_invoices)
            so_dpl.tax_ids = so_dpl.invoice_line_ids.tax_ids

        return res

    def action_view_source_sale_orders(self):
        return self._action_view_source_orders(
            "sale.order", "sale.action_sale_order", "sale.view_sale_order_form"
        )

    def create_sale_order(self):
        return self._create_order_from_invoice("sale.order")

    def _post_entries(self):
        posted = super()._post_entries()

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
            _debug.pipeline("outstanding_lines_added", move=invoice, lines=move_lines)
            for line in move_lines:
                invoice.js_add_outstanding_line(line.id)
        return posted

    def _reverse_moves(self, default_values_list=None, cancel=False):
        if not default_values_list:
            default_values_list = [{} for move in self]
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

    def _invoice_paid_hook(self):
        res = super()._invoice_paid_hook()
        todo = set()
        for invoice in self.filtered(lambda move: move.is_invoice()):
            for line in invoice.invoice_line_ids:
                todo.update(
                    (sale_line.order_id, invoice.name)
                    for sale_line in line.sale_line_ids
                )
        _debug.pipeline("invoice_paid_hook", moves=self, orders_notified=len(todo))
        for order, name in todo:
            order.message_post(body=self.env._("Invoice %s paid", name))
        return res

    def _get_sale_order_invoiced_amount(self, order):
        order_amount = 0
        for invoice in self:
            prices = sum(
                invoice.line_ids.filtered(
                    lambda x: (
                        x.display_type
                        not in ("line_note", "line_section", "line_subsection")
                        and order in x.sale_line_ids.order_id
                    ),
                ).mapped("price_total"),
            )
            order_amount += invoice.currency_id._convert(
                prices * -invoice.direction_sign,
                order.currency_id,
                invoice.company_id,
                invoice.invoice_date or invoice.date or fields.Date.context_today(self),
            )
        return order_amount

    def _get_partner_credit_warning_exclude_amount(self):
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
            _debug.logic(
                "credit_warning_excluded",
                move=self,
                order=order,
                amount=order_amount_company,
            )
        return exclude_amount

    def _is_downpayment(self):
        self.check_singleton()
        return (
            self.line_ids.sale_line_ids
            and all(
                sale_line.is_downpayment for sale_line in self.line_ids.sale_line_ids
            )
        ) or False
