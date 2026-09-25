from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.libs.debug_log import DebugLog
from odoo.tools import formatLang

from odoo.addons.trade.tools import direction_of

_debug = DebugLog(__name__)


def _depends_on_orders(model):
    return [model._order_field]


class MixinOrderAdvancePayment(models.AbstractModel):
    _name = "mixin.order.advance.payment"
    _description = "Order Invoicing Wizard"

    _order_field = ""
    _invoice_order_path = ""

    advance_payment_method = fields.Selection(
        selection=[
            ("delivered", "Regular invoice"),
            ("percentage", "Down payment (percentage)"),
            ("fixed", "Down payment (fixed amount)"),
        ],
        string="Create Invoice",
        default="delivered",
        required=True,
        help="A standard invoice is issued with all the order lines ready for invoicing,"
        "according to their invoicing policy (based on ordered or delivered quantity).",
    )
    has_down_payments = fields.Boolean(
        string="Has down payments",
        compute="_compute_has_down_payments",
    )
    deduct_down_payments = fields.Boolean(
        string="Deduct down payments",
        default=True,
    )
    amount = fields.Float(
        string="Down Payment",
        help="The percentage of amount to be invoiced in advance.",
    )
    fixed_amount = fields.Monetary(
        string="Down Payment Amount (Fixed)",
        help="The fixed amount to be invoiced in advance.",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        compute="_compute_currency_id",
        store=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        compute="_compute_company_id",
        store=True,
    )
    amount_taxinc_invoiced = fields.Monetary(
        string="Already invoiced",
        compute="_compute_amount_taxinc_invoiced",
        help="Only confirmed down payments are considered.",
    )
    display_draft_invoice_warning = fields.Boolean(
        compute="_compute_display_draft_invoice_warning"
    )
    consolidated_billing = fields.Boolean(
        default=True,
        help="Create one invoice for all orders related to same partner, same invoicing address"
        " and same delivery address.",
    )

    def _get_orders(self):
        return self[self._order_field]

    @api.depends(_depends_on_orders)
    def _compute_has_down_payments(self):
        for wizard in self:
            wizard.has_down_payments = bool(
                wizard._get_orders().line_ids.filtered("is_downpayment")
            )

    @api.depends(_depends_on_orders)
    def _compute_currency_id(self):
        self.currency_id = False
        for wizard in self:
            orders = wizard._get_orders()
            if len(orders) == 1:
                wizard.currency_id = orders.currency_id

    @api.depends(_depends_on_orders)
    def _compute_company_id(self):
        self.company_id = False
        for wizard in self:
            orders = wizard._get_orders()
            if len(orders) == 1:
                wizard.company_id = orders.company_id

    @api.depends(_depends_on_orders)
    def _compute_display_draft_invoice_warning(self):
        for wizard in self:
            invoice_states = (
                wizard._get_orders()._origin.sudo().invoice_ids.mapped("state")
            )
            wizard.display_draft_invoice_warning = "draft" in invoice_states

    @api.depends(_depends_on_orders)
    def _compute_amount_taxinc_invoiced(self):
        for wizard in self:
            wizard.amount_taxinc_invoiced = sum(
                wizard._get_orders()._origin.mapped("amount_taxinc_invoiced")
            )

    @api.onchange("advance_payment_method")
    def _onchange_advance_payment_method(self):
        if self.advance_payment_method == "percentage":
            amount = self.default_get(["amount"]).get("amount")
            return {"value": {"amount": amount}}
        return None

    def _check_amount_is_positive(self):
        for wizard in self:
            if (
                wizard.advance_payment_method == "percentage" and wizard.amount <= 0.00
            ) or (
                wizard.advance_payment_method == "fixed" and wizard.fixed_amount <= 0.00
            ):
                _debug.logic(
                    "down_payment_amount_rejected",
                    wizard=wizard,
                    method=wizard.advance_payment_method,
                    reason="not_positive",
                )
                raise UserError(
                    self.env._("The value of the down payment amount must be positive.")
                )
            if wizard.advance_payment_method == "percentage" and wizard.amount > 100.0:
                _debug.logic(
                    "down_payment_amount_rejected",
                    wizard=wizard,
                    method=wizard.advance_payment_method,
                    reason="over_100_percent",
                )
                raise UserError(
                    self.env._("The percentage of the down payment cannot exceed 100%.")
                )

    def create_invoices(self):
        self._check_amount_is_positive()
        orders = self._get_orders()
        invoices = self._create_invoices(orders)
        _debug.lifecycle(
            "advance_invoices_created", wizard=self, orders=orders, invoices=invoices
        )
        return orders.action_view_invoice(invoices=invoices)

    def view_draft_invoices(self):
        return {
            "name": self._get_draft_invoices_title(),
            "type": "ir.actions.act_window",
            "view_mode": "list",
            "views": [(False, "list"), (False, "form")],
            "res_model": "account.move",
            "domain": [
                (self._invoice_order_path, "in", self._get_orders().ids),
                ("state", "=", "draft"),
            ],
        }

    def _get_draft_invoices_title(self):
        return self.env._("Draft Invoices")

    def _get_down_payment_document_title(self):
        return self.env._("Down payment invoice")

    def _get_default_down_payment_account(self):
        return self.env["account.account"]

    def _create_invoices(self, orders):
        self.check_singleton()
        if self.advance_payment_method == "delivered":
            _debug.pipeline(
                "invoice_wizard",
                wizard=self,
                method="delivered",
                orders=orders,
                deduct=self.deduct_down_payments,
                consolidated=self.consolidated_billing,
            )
            return orders._create_invoices(
                final=self.deduct_down_payments, grouped=not self.consolidated_billing
            )
        orders.check_singleton()
        self = self.with_company(self.company_id)
        order = self._get_orders()

        AccountTax = self.env["account.tax"]
        order_lines = order.line_ids.filtered(lambda x: not x.display_type)
        base_lines = [
            line._prepare_base_line_for_taxes_computation() for line in order_lines
        ]
        AccountTax._add_tax_details_in_base_lines(base_lines, order.company_id)
        AccountTax._round_base_lines_tax_details(base_lines, order.company_id)

        if self.advance_payment_method == "percentage":
            amount_type = "percent"
            amount = self.amount
        else:
            amount_type = "fixed"
            amount = self.fixed_amount

        _debug.pipeline(
            "down_payment_base_lines",
            wizard=self,
            order=order,
            lines=order_lines,
            amount_type=amount_type,
            amount=amount,
        )
        down_payment_base_lines = AccountTax._prepare_down_payment_lines(
            base_lines=base_lines,
            company=self.company_id,
            amount_type=amount_type,
            amount=amount,
            computation_key=f"down_payment,{self.id}",
        )

        order._get_down_payment_section_line()
        down_payment_lines = order._create_down_payment_lines_from_base_lines(
            down_payment_base_lines
        )

        invoice_values = self.with_context(
            accounts=[
                base_line["account_id"]
                or self._get_down_payment_account(base_line["product_id"])
                for base_line in down_payment_base_lines
            ],
        )._prepare_down_payment_invoice_values(
            order=order,
            down_payment_lines=down_payment_lines,
        )
        invoice_sudo = self.env["account.move"].sudo().create(invoice_values)
        _debug.lifecycle(
            "down_payment_invoice_created",
            order=order,
            invoice=invoice_sudo,
            lines=down_payment_lines,
        )

        invoice = invoice_sudo.sudo(self.env.su)
        poster = (self.env.user._is_internal() and self.env.user.id) or SUPERUSER_ID
        invoice.with_user(poster).message_post_with_source(
            "mail.message_origin_link",
            render_values={"self": invoice, "origin": order},
            subtype_xmlid="mail.mt_note",
        )
        title = self._get_down_payment_document_title()
        order.with_user(poster).message_post(
            body=self.env._("%s has been created", invoice._get_html_link(title=title)),
        )
        return invoice

    def _prepare_down_payment_invoice_values(self, order, down_payment_lines):
        self.check_singleton()
        accounts = self.env.context.get("accounts")
        default_account = self._get_default_down_payment_account()
        return {
            **order._prepare_invoice_vals(),
            "invoice_line_ids": [
                Command.create(
                    self._prepare_down_payment_invoice_line_values(
                        order, line, default_account or account
                    )
                )
                for line, account in zip(down_payment_lines, accounts, strict=True)
            ],
        }

    def _prepare_down_payment_invoice_line_values(self, order, line, account):
        self.check_singleton()
        self = self.with_context(lang=order._get_lang())

        if self.advance_payment_method == "percentage":
            name = self.env._("Down payment of %s%%", formatLang(self.env, self.amount))
        else:
            name = self.env._("Down Payment")

        return line._prepare_aml_vals(
            name=name,
            quantity=1.0,
            **({"account_id": account.id} if account else {}),
        )

    def _get_down_payment_account(self, product):
        orders = self._get_orders()
        key = direction_of(orders).product_account_key
        product_account = product.product_tmpl_id._get_product_accounts(
            fiscal_pos=orders.fiscal_position_id
        )
        _debug.logic(
            "down_payment_account",
            product=product,
            by="downpayment" if product_account.get("downpayment") else key,
        )
        return product_account.get("downpayment") or product_account.get(key)
