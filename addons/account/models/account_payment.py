from itertools import zip_longest

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import SQL


class AccountPayment(models.Model):
    _name = "account.payment"
    _inherit = [
        "mixin.mail.thread.main.attachment",
        "mixin.mail.activity",
        "mixin.payment.qr.code",
    ]
    _description = "Payments"
    _order = "date desc, name desc"
    _check_company_auto = True

    name = fields.Char(string="Number", compute="_compute_name", store=True)
    date = fields.Date(default=fields.Date.context_today, required=True, tracking=True)
    move_id = fields.Many2one(
        comodel_name="account.move",
        string="Journal Entry",
        index=True,
        copy=False,
        check_company=True,
    )
    journal_id = fields.Many2one(
        comodel_name="account.journal",
        compute="_compute_journal_id",
        store=True,
        readonly=False,
        precompute=True,
        check_company=True,
        index=False,
        required=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        compute="_compute_company_id",
        store=True,
        readonly=False,
        precompute=True,
        index=False,
        required=True,
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("in_process", "In Process"),
            ("paid", "Paid"),
            ("canceled", "Canceled"),
            ("rejected", "Rejected"),
        ],
        required=True,
        default="draft",
        compute="_compute_state",
        store=True,
        readonly=False,
        tracking=True,
        copy=False,
    )
    is_reconciled = fields.Boolean(
        string="Is Reconciled",
        store=True,
        compute="_compute_reconciliation_status",
    )
    is_matched = fields.Boolean(
        string="Is Matched With a Bank Statement",
        store=True,
        compute="_compute_reconciliation_status",
    )
    is_sent = fields.Boolean(string="Is Sent", readonly=True, copy=False)
    available_partner_bank_ids = fields.Many2many(
        comodel_name="res.partner.bank",
        compute="_compute_available_partner_bank_ids",
    )
    partner_bank_id = fields.Many2one(
        "res.partner.bank",
        string="Recipient Bank Account",
        readonly=False,
        store=True,
        tracking=True,
        compute="_compute_partner_bank_id",
        domain="[('id', 'in', available_partner_bank_ids)]",
        check_company=True,
        ondelete="restrict",
    )
    qr_code = fields.Html(string="QR Code URL", compute="_compute_qr_code")
    paired_internal_transfer_payment_id = fields.Many2one(
        "account.payment",
        index="btree_not_null",
        help="When an internal transfer is posted, a paired payment is created. "
        "They are cross referenced through this field",
        copy=False,
    )

    payment_method_line_id = fields.Many2one(
        "account.payment.method.line",
        string="Payment Method",
        readonly=False,
        store=True,
        copy=False,
        compute="_compute_payment_method_line_id",
        domain="[('id', 'in', available_payment_method_line_ids)]",
        help="Manual: Pay or Get paid by any method outside of Odoo.\n"
        "Payment Providers: Each payment provider has its own Payment Method. Request a transaction on/to a card thanks to a payment token saved by the partner when buying or subscribing online.\n"
        "Check: Pay bills by check and print it from Odoo.\n"
        "Batch Deposit: Collect several customer checks at once generating and submitting a batch deposit to your bank. Module account_batch_payment is necessary.\n"
        "SEPA Credit Transfer: Pay in the SEPA zone by submitting a SEPA Credit Transfer file to your bank. Module account_iso20022 is necessary.\n"
        "SEPA Direct Debit: Get paid in the SEPA zone thanks to a mandate your partner will have granted to you. Module account_iso20022 is necessary.\n"
        "U.S. ISO20022: Pay in the US by submitting an ISO20022 file to your bank. Module account_iso20022 is necessary.\n",
    )
    available_payment_method_line_ids = fields.Many2many(
        "account.payment.method.line",
        compute="_compute_available_payment_method_line_ids",
    )
    payment_method_id = fields.Many2one(
        related="payment_method_line_id.payment_method_id",
        string="Method",
        tracking=True,
        store=True,
    )
    available_journal_ids = fields.Many2many(
        comodel_name="account.journal",
        compute="_compute_available_journal_ids",
    )

    amount = fields.Monetary(currency_field="currency_id")
    payment_type = fields.Selection(
        [
            ("outbound", "Send"),
            ("inbound", "Receive"),
        ],
        string="Payment Type",
        default="inbound",
        required=True,
        tracking=True,
    )
    partner_type = fields.Selection(
        [
            ("customer", "Customer"),
            ("supplier", "Vendor"),
        ],
        default="customer",
        tracking=True,
        required=True,
    )
    memo = fields.Char(string="Memo", tracking=True, inverse="_inverse_memo")
    payment_reference = fields.Char(
        string="Payment Reference",
        copy=False,
        tracking=True,
        help="Reference of the document used to issue this payment. Eg. check number, file name, etc.",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        compute="_compute_currency_id",
        store=True,
        readonly=False,
        precompute=True,
        help="The payment's currency.",
    )
    company_currency_id = fields.Many2one(
        string="Company Currency",
        related="company_id.currency_id",
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Customer/Vendor",
        ondelete="restrict",
        domain="['|', ('parent_id','=', False), ('is_company','=', True)]",
        tracking=True,
        check_company=True,
    )
    outstanding_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Outstanding Account",
        store=True,
        index="btree_not_null",
        compute="_compute_outstanding_account_id",
        check_company=True,
    )
    destination_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Destination Account",
        store=True,
        readonly=False,
        compute="_compute_destination_account_id",
        domain="[('account_type', 'in', ('asset_receivable', 'liability_payable'))]",
        check_company=True,
    )

    invoice_ids = fields.Many2many(
        string="Invoices",
        comodel_name="account.move",
        relation="account_move__account_payment",
        column1="payment_id",
        column2="invoice_id",
        copy=False,
    )
    reconciled_invoice_ids = fields.Many2many(
        "account.move",
        string="Reconciled Invoices",
        compute="_compute_stat_buttons_from_reconciliation",
        search="_search_reconciled_invoice_ids",
        help="Invoices whose journal items have been reconciled with these payments.",
    )
    reconciled_invoices_count = fields.Count(
        "reconciled_invoice_ids",
        string="# Reconciled Invoices",
    )

    reconciled_invoices_type = fields.Selection(
        [("credit_note", "Credit Note"), ("invoice", "Invoice")],
        compute="_compute_stat_buttons_from_reconciliation",
    )
    reconciled_bill_ids = fields.Many2many(
        "account.move",
        string="Reconciled Bills",
        compute="_compute_stat_buttons_from_reconciliation",
        search="_search_reconciled_bill_ids",
        help="Bills whose journal items have been reconciled with these payments.",
    )
    reconciled_bills_count = fields.Count(
        "reconciled_bill_ids",
        string="# Reconciled Bills",
    )
    reconciled_statement_line_ids = fields.Many2many(
        comodel_name="account.bank.statement.line",
        string="Reconciled Statement Lines",
        compute="_compute_stat_buttons_from_reconciliation",
        help="Statements lines matched to this payment",
    )
    reconciled_statement_lines_count = fields.Count(
        "reconciled_statement_line_ids",
        string="# Reconciled Statement Lines",
    )

    payment_method_code = fields.Char(
        related="payment_method_line_id.code",
    )
    payment_receipt_title = fields.Char(
        compute="_compute_payment_receipt_title",
    )

    need_cancel_request = fields.Boolean(
        related="move_id.need_cancel_request",
    )
    show_partner_bank_account = fields.Boolean(
        compute="_compute_show_require_partner_bank"
    )
    require_partner_bank_account = fields.Boolean(
        compute="_compute_show_require_partner_bank"
    )
    country_code = fields.Char(
        related="company_id.account_fiscal_country_id.code",
    )
    amount_signed = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_amount_signed",
        tracking=True,
        help="Negative value of amount field if payment_type is outbound",
    )
    amount_company_currency_signed = fields.Monetary(
        currency_field="company_currency_id",
        compute="_compute_amount_company_currency_signed",
        store=True,
    )
    duplicate_payment_ids = fields.Many2many(
        comodel_name="account.payment", compute="_compute_duplicate_payment_ids"
    )
    attachment_ids = fields.One2many("ir.attachment", "res_id", string="Attachments")

    _check_amount_not_negative = models.Constraint(
        "CHECK(amount >= 0.0)",
        "The payment amount cannot be negative.",
    )
    _journal_id_company_id_idx = models.Index("(journal_id, company_id)")
    _unmatched_idx = models.Index(
        "(journal_id, company_id) WHERE is_matched IS NOT TRUE"
    )

    @api.model
    def _get_valid_payment_account_types(self):
        return ["asset_receivable", "liability_payable"]

    def _seek_for_lines(self):
        self.ensure_one()

        empty = self.env["account.move.line"]
        buckets = ([], [], [])
        valid_account_types = self._get_valid_payment_account_types()
        liquidity_accounts = self._get_valid_liquidity_accounts()
        for line in self.move_id.line_ids:
            if line.account_id in liquidity_accounts:
                buckets[0].append(line.id)
            elif (
                line.account_id.account_type in valid_account_types
                or line.account_id == line.company_id.transfer_account_id
            ):
                buckets[1].append(line.id)
            else:
                buckets[2].append(line.id)

        lines = [empty.browse(bucket) for bucket in buckets]
        if len(lines[2]) == 1:
            for i in (0, 1):
                if not lines[i]:
                    lines[i] = lines[2]
                    lines[2] = empty

        return lines

    def _get_valid_liquidity_accounts(self):
        self.ensure_one()
        return (
            self.journal_id.default_account_id
            | self.payment_method_line_id.payment_account_id
            | self.journal_id.inbound_payment_method_line_ids.payment_account_id
            | self.journal_id.outbound_payment_method_line_ids.payment_account_id
            | self.outstanding_account_id
        )

    def _valid_payment_states(self):
        return (
            ["in_process", "paid"]
            if self.env["account.move"]._get_invoice_in_payment_state() == "paid"
            else ["in_process"]
        )

    def _get_aml_default_display_name_list(self):
        self.ensure_one()
        label = (
            self.payment_method_line_id.name
            if self.payment_method_line_id
            else _("No Payment Method")
        )

        if self.memo:
            return [
                ("label", label),
                ("sep", ": "),
                ("memo", self.memo),
            ]
        return [
            ("label", label),
        ]

    def _prepare_move_withholding_lines(self, default_values):
        self.ensure_one()
        return []

    def _prepare_move_liquidity_lines(self, default_values):
        self.ensure_one()
        return [
            {
                "name": default_values["name"],
                "date_maturity": self.date,
                "partner_id": self.partner_id.id,
                "account_id": self.outstanding_account_id.id,
                "currency_id": self.currency_id.id,
                "balance": default_values["balance"],
                "amount_currency": default_values["amount_currency"],
            }
        ]

    def _prepare_move_counterpart_lines(self, default_values):
        self.ensure_one()
        return [
            {
                "name": default_values["name"],
                "date_maturity": self.date,
                "partner_id": self.partner_id.id,
                "account_id": self.destination_account_id.id,
                "currency_id": self.currency_id.id,
                "balance": default_values["balance"],
                "amount_currency": default_values["amount_currency"],
            }
        ]

    def _prepare_move_lines_per_type(
        self, write_off_line_vals=None, force_balance=None
    ):
        self.ensure_one()

        if not self.outstanding_account_id:
            raise UserError(
                _(
                    "You can't create a new payment without an outstanding payments/receipts account set either on the company or the %(payment_method)s payment method in the %(journal)s journal.",
                    payment_method=self.payment_method_line_id.name,
                    journal=self.journal_id.display_name,
                )
            )

        line_name = "".join(
            x[1] for x in self._get_aml_default_display_name_list() if x[1]
        )

        write_off_lines = write_off_line_vals or []
        write_off_amount_currency = sum(x["amount_currency"] for x in write_off_lines)
        write_off_balance = sum(x["balance"] for x in write_off_lines)

        withholding_lines = self._prepare_move_withholding_lines({})
        withholding_amount_currency = sum(
            x["amount_currency"] for x in withholding_lines
        )
        withholding_balance = sum(x["balance"] for x in withholding_lines)

        sign = -1 if self.payment_type == "outbound" else 1
        liquidity_amount_currency = sign * self.amount

        if not write_off_line_vals and force_balance is not None:
            liquidity_balance = sign * abs(force_balance)
        else:
            liquidity_balance = self.currency_id._convert(
                liquidity_amount_currency,
                self.company_id.currency_id,
                self.company_id,
                self.date,
            )
        liquidity_amount_currency -= withholding_amount_currency
        liquidity_balance -= withholding_balance

        liquidity_lines = self._prepare_move_liquidity_lines(
            {
                "name": line_name,
                "balance": liquidity_balance,
                "amount_currency": liquidity_amount_currency,
            }
        )

        counterpart_amount_currency = (
            -liquidity_amount_currency
            - write_off_amount_currency
            - withholding_amount_currency
        )
        counterpart_balance = (
            -liquidity_balance - write_off_balance - withholding_balance
        )
        counterpart_lines = self._prepare_move_counterpart_lines(
            {
                "name": line_name,
                "balance": counterpart_balance,
                "amount_currency": counterpart_amount_currency,
            }
        )

        return {
            "liquidity_lines": liquidity_lines,
            "counterpart_lines": counterpart_lines,
            "write_off_lines": write_off_lines,
            "withholding_lines": withholding_lines,
        }

    def _prepare_move_line_default_vals(
        self, write_off_line_vals=None, force_balance=None
    ):
        self.ensure_one()

        line_vals_per_type = self._prepare_move_lines_per_type(
            write_off_line_vals=write_off_line_vals, force_balance=force_balance
        )
        line_vals = []
        for sub_line_vals in line_vals_per_type.values():
            line_vals += sub_line_vals
        return line_vals

    @api.depends("move_id.name", "state", "company_id", "date")
    def _compute_name(self):
        for payment in self:
            if (
                payment.id
                and (
                    not payment.name
                    or (payment.move_id and payment.name != payment.move_id.name)
                )
                and payment.state in ("in_process", "paid")
            ):
                payment.name = payment.move_id.name or self.env[
                    "ir.sequence"
                ].with_company(payment.company_id).next_by_code(
                    "account.payment",
                    sequence_date=payment.date,
                )

    @api.depends("company_id", "partner_id", "payment_type")
    def _compute_journal_id(self):
        default_journal_by_company = {}
        for payment in self:
            partner = payment.partner_id
            payment_type = (
                payment.payment_type
                if payment.payment_type in ("inbound", "outbound")
                else None
            )
            if not payment._origin and partner and payment_type:
                field_name = f"property_{payment_type}_payment_method_line_id"
                default_payment_method_line = payment.partner_id.with_company(
                    payment.company_id
                )[field_name]
                journal = default_payment_method_line.journal_id
                if journal:
                    payment.journal_id = journal
                    continue

            company = payment.company_id or self.env.company
            if not payment.journal_id or company != payment.journal_id.company_id:
                if company not in default_journal_by_company:
                    default_journal_by_company[company] = self.env[
                        "account.journal"
                    ].search(
                        [
                            *self.env["account.journal"]._check_company_domain(company),
                            ("type", "in", ["bank", "cash", "credit"]),
                        ],
                        limit=1,
                    )
                payment.journal_id = default_journal_by_company[company]

    @api.depends("journal_id")
    def _compute_company_id(self):
        for payment in self:
            if payment.journal_id.company_id not in payment.company_id.parent_ids:
                payment.company_id = (
                    payment.journal_id.company_id or self.env.company
                )._accessible_branches()[:1]

    @api.depends(
        "reconciled_invoice_ids.payment_state",
        "reconciled_bill_ids.payment_state",
        "move_id.line_ids.amount_residual",
    )
    def _compute_state(self):
        for payment in self:
            if not payment.state:
                payment.state = "draft"
            if (move := payment.move_id) and payment.state in ("paid", "in_process"):
                liquidity, _counterpart, _writeoff = payment._seek_for_lines()
                payment.state = (
                    "paid"
                    if move.company_currency_id.is_zero(
                        sum(liquidity.mapped("amount_residual"))
                    )
                    or not any(liquidity.account_id.mapped("reconcile"))
                    else "in_process"
                )
            if (
                payment.state == "in_process"
                and (
                    moves := (
                        payment.reconciled_invoice_ids | payment.reconciled_bill_ids
                    )
                )
                and all(invoice.payment_state == "paid" for invoice in moves)
            ):
                payment.state = "paid"

    @api.depends(
        "move_id.line_ids.amount_residual",
        "move_id.line_ids.amount_residual_currency",
        "move_id.line_ids.account_id",
        "state",
        "amount",
        "currency_id",
        "company_id.currency_id",
        "outstanding_account_id",
        "journal_id.default_account_id",
    )
    def _compute_reconciliation_status(self):
        for pay in self:
            liquidity_lines, counterpart_lines, writeoff_lines = pay._seek_for_lines()

            if not pay.outstanding_account_id:
                pay.is_reconciled = False
                pay.is_matched = pay.state == "paid"
            elif not pay.currency_id or not pay.id or not pay.move_id:
                pay.is_reconciled = False
                pay.is_matched = False
            elif pay.currency_id.is_zero(pay.amount):
                pay.is_reconciled = True
                pay.is_matched = True
            else:
                residual_field = (
                    "amount_residual"
                    if pay.currency_id == pay.company_id.currency_id
                    else "amount_residual_currency"
                )
                if (
                    pay.journal_id.default_account_id
                    and pay.journal_id.default_account_id in liquidity_lines.account_id
                ):
                    pay.is_matched = True
                else:
                    pay.is_matched = pay.currency_id.is_zero(
                        sum(liquidity_lines.mapped(residual_field))
                    )

                reconcile_lines = (counterpart_lines + writeoff_lines).filtered(
                    lambda line: line.account_id.reconcile
                )
                pay.is_reconciled = pay.currency_id.is_zero(
                    sum(reconcile_lines.mapped(residual_field))
                )

    @api.model
    def _get_method_codes_using_bank_account(self):
        return ["manual"]

    @api.model
    def _get_method_codes_needing_bank_account(self):
        return []

    def action_view_business_doc(self):
        return {
            "name": _("Payment"),
            "type": "ir.actions.act_window",
            "views": [(False, "form")],
            "res_model": "account.payment",
            "res_id": self.id,
        }

    @api.depends("payment_method_code", "journal_id.type", "state")
    def _compute_show_require_partner_bank(self):
        for payment in self:
            if payment.journal_id.type == "cash":
                payment.show_partner_bank_account = False
            else:
                payment.show_partner_bank_account = (
                    payment.payment_method_code
                    in self._get_method_codes_using_bank_account()
                )
            payment.require_partner_bank_account = (
                payment.state == "draft"
                and payment.payment_method_code
                in self._get_method_codes_needing_bank_account()
            )

    @api.depends(
        "move_id.line_ids.balance",
        "move_id.line_ids.account_id",
        "amount",
        "payment_type",
        "currency_id",
        "date",
        "company_id",
        "company_currency_id",
    )
    def _compute_amount_company_currency_signed(self):
        for payment in self:
            if payment.move_id:
                liquidity_lines = payment._seek_for_lines()[0]
                payment.amount_company_currency_signed = sum(
                    liquidity_lines.mapped("balance")
                )
            else:
                payment.amount_company_currency_signed = payment.currency_id._convert(
                    from_amount=payment.amount_signed,
                    to_currency=payment.company_currency_id,
                    company=payment.company_id,
                    date=payment.date,
                )

    @api.depends("amount", "payment_type")
    def _compute_amount_signed(self):
        for payment in self:
            if payment.payment_type == "outbound":
                payment.amount_signed = -payment.amount
            else:
                payment.amount_signed = payment.amount

    @api.depends(
        "partner_id", "company_id", "payment_type", "journal_id.bank_account_id"
    )
    def _compute_available_partner_bank_ids(self):
        for pay in self:
            if pay.payment_type == "inbound":
                pay.available_partner_bank_ids = pay.journal_id.bank_account_id
            else:
                pay.available_partner_bank_ids = pay.partner_id.bank_ids.filtered(
                    lambda x, pay=pay: x.company_id.id in (False, pay.company_id.id)
                )._origin

    @api.depends("available_partner_bank_ids", "journal_id")
    def _compute_partner_bank_id(self):
        for pay in self:
            if pay.partner_bank_id not in pay.available_partner_bank_ids:
                pay.partner_bank_id = pay.available_partner_bank_ids[:1]._origin

    @api.depends("available_payment_method_line_ids", "partner_id", "company_id")
    def _compute_payment_method_line_id(self):
        for pay in self:
            available_payment_method_lines = pay.available_payment_method_line_ids
            partner = pay.partner_id.with_company(pay.company_id)
            inbound_payment_method = partner.property_inbound_payment_method_line_id
            outbound_payment_method = partner.property_outbound_payment_method_line_id
            if (
                pay.payment_type == "inbound"
                and inbound_payment_method.id in available_payment_method_lines.ids
            ):
                pay.payment_method_line_id = inbound_payment_method
            elif (
                pay.payment_type == "outbound"
                and outbound_payment_method.id in available_payment_method_lines.ids
            ):
                pay.payment_method_line_id = outbound_payment_method
            elif pay.payment_method_line_id.id in available_payment_method_lines.ids:
                continue
            elif available_payment_method_lines:
                pay.payment_method_line_id = available_payment_method_lines[0]._origin
            else:
                pay.payment_method_line_id = False

    @api.depends("payment_type", "journal_id", "currency_id")
    def _compute_available_payment_method_line_ids(self):
        for pay in self:
            pay.available_payment_method_line_ids = (
                pay.journal_id._get_available_payment_method_lines(pay.payment_type)
            )
            to_exclude = pay._get_payment_method_codes_to_exclude()
            if to_exclude:
                pay.available_payment_method_line_ids = (
                    pay.available_payment_method_line_ids.filtered(
                        lambda x, to_exclude=to_exclude: x.code not in to_exclude
                    )
                )

    @api.depends("payment_type", "company_id")
    def _compute_available_journal_ids(self):
        journals_per_company = {}
        for pay in self:
            company = pay.company_id or self.env.company
            if company not in journals_per_company:
                journals_per_company[company] = self.env["account.journal"].search(
                    [
                        "|",
                        ("company_id", "parent_of", company.id),
                        ("company_id", "child_of", company.id),
                        ("type", "in", ("bank", "cash", "credit")),
                    ]
                )
            method_lines = (
                "inbound_payment_method_line_ids"
                if pay.payment_type == "inbound"
                else "outbound_payment_method_line_ids"
            )
            pay.available_journal_ids = journals_per_company[company].filtered(
                method_lines
            )

    def _get_payment_method_codes_to_exclude(self):
        self.ensure_one()
        return []

    @api.depends("journal_id.currency_id", "company_id.currency_id")
    def _compute_currency_id(self):
        for pay in self:
            pay.currency_id = pay.journal_id.currency_id or pay.company_id.currency_id

    @api.depends("payment_method_line_id")
    def _compute_outstanding_account_id(self):
        for pay in self:
            pay.outstanding_account_id = pay.payment_method_line_id.payment_account_id

    @api.depends("journal_id", "partner_id", "partner_type")
    def _compute_destination_account_id(self):
        self.destination_account_id = False
        fallback_account = {}

        def _fallback(company, account_type):
            key = (company, account_type)
            if key not in fallback_account:
                fallback_account[key] = (
                    self.env["account.account"]
                    .with_company(company)
                    .search(
                        [
                            *self.env["account.account"]._check_company_domain(company),
                            ("account_type", "=", account_type),
                        ],
                        limit=1,
                    )
                )
            return fallback_account[key]

        for pay in self:
            if pay.partner_type == "customer":
                if pay.partner_id:
                    pay.destination_account_id = pay.partner_id.with_company(
                        pay.company_id
                    ).property_account_receivable_id
                else:
                    pay.destination_account_id = _fallback(
                        pay.company_id, "asset_receivable"
                    )
            elif pay.partner_type == "supplier":
                if pay.partner_id:
                    pay.destination_account_id = pay.partner_id.with_company(
                        pay.company_id
                    ).property_account_payable_id
                else:
                    pay.destination_account_id = _fallback(
                        pay.company_id, "liability_payable"
                    )

    @api.depends(
        "partner_bank_id",
        "amount",
        "memo",
        "currency_id",
        "journal_id",
        "move_id.state",
        "payment_method_line_id",
        "payment_type",
        "state",
    )
    def _compute_qr_code(self):
        for pay in self:
            pay.qr_code = (
                pay._render_payment_qr_code(pay.amount, pay.memo)
                if pay.state in ("draft", "in_process")
                else False
            )

    @api.depends(
        "move_id.line_ids.matched_debit_ids",
        "move_id.line_ids.matched_credit_ids",
        "invoice_ids",
    )
    def _compute_stat_buttons_from_reconciliation(self):
        stored_payments = self.filtered("id")
        if not stored_payments:
            self.reconciled_invoice_ids = False
            self.reconciled_invoices_type = False
            self.reconciled_bill_ids = False
            self.reconciled_statement_line_ids = False
            return

        self.env["account.payment"].flush_model(
            fnames=["move_id", "outstanding_account_id"]
        )
        self.env["account.move"].flush_model(
            fnames=["move_type", "origin_payment_id", "statement_line_id"]
        )
        self.env["account.move.line"].flush_model(
            fnames=["move_id", "account_id", "statement_line_id"]
        )
        self.env["account.partial.reconcile"].flush_model(
            fnames=["debit_move_id", "credit_move_id"]
        )

        invoices_per_payment = self.env.execute_query(
            SQL(
                """
            SELECT
                payment.id,
                ARRAY_AGG(DISTINCT invoice.id) AS invoice_ids,
                invoice.move_type
            FROM account_payment payment
            JOIN account_move move ON move.id = payment.move_id
            JOIN account_move_line line ON line.move_id = move.id
            JOIN account_partial_reconcile part ON
                part.debit_move_id = line.id
                OR
                part.credit_move_id = line.id
            JOIN account_move_line counterpart_line ON
                part.debit_move_id = counterpart_line.id
                OR
                part.credit_move_id = counterpart_line.id
            JOIN account_move invoice ON invoice.id = counterpart_line.move_id
            JOIN account_account account ON account.id = line.account_id
            WHERE account.account_type IN ('asset_receivable', 'liability_payable')
                AND payment.id = ANY(%(payment_ids)s)
                AND line.id != counterpart_line.id
                AND invoice.move_type = ANY(%(move_types)s)
            GROUP BY payment.id, invoice.move_type
        """,
                payment_ids=stored_payments.ids,
                move_types=list(
                    self.env["account.move"].get_sale_types(True)
                    + self.env["account.move"].get_purchase_types(True)
                ),
            )
        )

        for pay in self:
            pay.reconciled_invoice_ids = pay.invoice_ids.filtered(
                lambda m: m.is_sale_document(True)
            )
            pay.reconciled_bill_ids = pay.invoice_ids.filtered(
                lambda m: m.is_purchase_document(True)
            )

        sale_types = self.env["account.move"].get_sale_types(True)
        for payment_id, invoice_ids, move_type in invoices_per_payment:
            pay = self.browse(payment_id)
            invoices = self.env["account.move"].browse(invoice_ids)
            if move_type in sale_types:
                pay.reconciled_invoice_ids |= invoices
            else:
                pay.reconciled_bill_ids |= invoices

        query_res = dict(
            self.env.execute_query(
                SQL(
                    """
            SELECT
                payment.id,
                ARRAY_AGG(DISTINCT counterpart_line.statement_line_id) AS statement_line_ids
            FROM account_payment payment
            JOIN account_move move ON move.id = payment.move_id
            JOIN account_move_line line ON line.move_id = move.id
            JOIN account_account account ON account.id = line.account_id
            JOIN account_partial_reconcile part ON
                part.debit_move_id = line.id
                OR
                part.credit_move_id = line.id
            JOIN account_move_line counterpart_line ON
                part.debit_move_id = counterpart_line.id
                OR
                part.credit_move_id = counterpart_line.id
            WHERE account.id = payment.outstanding_account_id
                AND payment.id IN %(payment_ids)s
                AND line.id != counterpart_line.id
                AND counterpart_line.statement_line_id IS NOT NULL
            GROUP BY payment.id
        """,
                    payment_ids=tuple(stored_payments.ids),
                )
            )
        )

        for pay in self:
            statement_line_ids = query_res.get(pay.id, [])
            pay.reconciled_statement_line_ids = [Command.set(statement_line_ids)]
            if (
                len(pay.reconciled_invoice_ids.mapped("move_type")) == 1
                and pay.reconciled_invoice_ids[0].move_type == "out_refund"
            ):
                pay.reconciled_invoices_type = "credit_note"
            else:
                pay.reconciled_invoices_type = "invoice"

    @api.depends("payment_type", "partner_type")
    def _compute_payment_receipt_title(self):
        for pay in self:
            if pay.payment_type == "outbound" and pay.partner_type == "supplier":
                pay.payment_receipt_title = _("Remittance Advice")
            elif (
                pay.payment_type == "outbound" and pay.partner_type == "customer"
            ) or (pay.payment_type == "inbound" and pay.partner_type == "supplier"):
                pay.payment_receipt_title = _("Refund Confirmation")
            else:
                pay.payment_receipt_title = _("Payment Receipt")

    @api.depends(
        "partner_id",
        "amount",
        "date",
        "payment_type",
        "company_id",
        "currency_id",
        "state",
    )
    def _compute_duplicate_payment_ids(self):
        payment_to_duplicate_move = self._get_duplicate_reference()
        for payment in self:
            payment.duplicate_payment_ids = payment_to_duplicate_move.get(
                payment._origin.id, self.env["account.payment"]
            )

    def _search_reconciled_move_ids(self, operator, value, move_filter=None):
        if operator not in ("in", "="):
            return NotImplemented
        moves = self.env["account.move"].browse(value).exists()
        if move_filter is not None:
            moves = moves.filtered(move_filter)
        return [("id", "in", moves.reconciled_payment_ids.ids)]

    def _search_reconciled_invoice_ids(self, operator, value):
        return self._search_reconciled_move_ids(
            operator, value, lambda move: move.is_sale_document(True)
        )

    def _search_reconciled_bill_ids(self, operator, value):
        return self._search_reconciled_move_ids(
            operator, value, lambda move: move.is_purchase_document(True)
        )

    def _get_duplicate_reference(self, matching_states=("draft", "in_process")):
        payments = self.filtered(
            lambda p: p.partner_id and p.amount and p.state != "in_process"
        )
        if not payments:
            return {}

        used_fields = (
            "company_id",
            "partner_id",
            "date",
            "state",
            "amount",
            "payment_type",
            "currency_id",
        )
        self.flush_model(used_fields)

        payment_table_and_alias = SQL("account_payment AS payment")
        if not self.ids:
            self.ensure_one()
            values = {
                field_name: self._fields[field_name].convert_to_write(
                    self[field_name], self
                )
                or None
                for field_name in used_fields
            }
            values["id"] = self._origin.id or 0
            casted_values = SQL(", ").join(
                SQL(
                    "%s::%s",
                    value,
                    SQL.identifier(self._fields[field_name].column_type[0]),
                )
                for field_name, value in values.items()
            )
            column_names = SQL(", ").join(
                SQL.identifier(field_name) for field_name in values
            )
            payment_table_and_alias = SQL(
                "(VALUES (%s)) AS payment(%s)", casted_values, column_names
            )

        query = SQL(
            """
                SELECT payment.id AS payment_id,
                       ARRAY_AGG(DISTINCT duplicate_payment.id) AS duplicate_payment_ids
                  FROM %(payment_table_and_alias)s
                  JOIN account_payment AS duplicate_payment ON payment.id != duplicate_payment.id
                                                           AND payment.partner_id = duplicate_payment.partner_id
                                                           AND payment.company_id = duplicate_payment.company_id
                                                           AND payment.date = duplicate_payment.date
                                                           AND payment.payment_type = duplicate_payment.payment_type
                                                           AND payment.amount = duplicate_payment.amount
                                                           AND payment.currency_id = duplicate_payment.currency_id
                                                           AND duplicate_payment.state IN %(matching_states)s
                 WHERE payment.id = ANY(%(payments)s)
              GROUP BY payment.id
            """,
            payment_table_and_alias=payment_table_and_alias,
            matching_states=tuple(matching_states),
            payments=payments.ids or [0],
        )

        return {
            payment_id: self.env["account.payment"].browse(duplicate_ids)
            for payment_id, duplicate_ids in self.env.execute_query(query)
        }

    def _inverse_memo(self):
        for payment in self:
            move = payment.move_id
            if move:
                move.ref = payment.memo

    @api.constrains("payment_method_line_id")
    def _check_payment_method_line_id(self):
        for pay in self:
            if not pay.payment_method_line_id:
                raise ValidationError(
                    _("Please define a payment method line on your payment.")
                )
            if (
                pay.payment_method_line_id.journal_id
                and pay.payment_method_line_id.journal_id != pay.journal_id
            ):
                raise ValidationError(
                    _(
                        "The selected payment method is not available for this payment, please select the payment method again."
                    )
                )

    @api.constrains("state", "move_id")
    def _check_move_id(self):
        for payment in self:
            if (
                payment.state not in ("draft", "canceled")
                and not payment.move_id
                and payment.outstanding_account_id
            ):
                raise ValidationError(
                    _(
                        "A payment with an outstanding account cannot be confirmed without having a journal entry."
                    )
                )

    @api.model_create_multi
    def create(self, vals_list):
        write_off_line_vals_list = []
        force_balance_vals_list = []
        linecomplete_line_vals_list = []

        for vals in vals_list:
            write_off_line_vals_list.append(vals.pop("write_off_line_vals", None))

            force_balance_vals_list.append(vals.pop("force_balance", None))

            linecomplete_line_vals_list.append(vals.pop("line_ids", None))

        payments = super().create(vals_list)

        accounting_installed = (
            self.env["account.move"]._get_invoice_in_payment_state() == "in_payment"
        )

        for i, (pay, vals) in enumerate(zip(payments, vals_list, strict=True)):
            if (
                not accounting_installed and not pay.outstanding_account_id
            ) or self.env.context.get("force_payment_move"):
                outstanding_account = pay._get_outstanding_account(pay.payment_type)
                pay.outstanding_account_id = outstanding_account.id

            if (
                write_off_line_vals_list[i] is not None
                or force_balance_vals_list[i] is not None
                or linecomplete_line_vals_list[i] is not None
            ):
                pay._generate_journal_entry(
                    write_off_line_vals=write_off_line_vals_list[i],
                    force_balance=force_balance_vals_list[i],
                    line_ids=linecomplete_line_vals_list[i],
                )
                if move_vals := {
                    fname: value
                    for fname, value in vals.items()
                    if self._fields[fname].related
                    and (self._fields[fname].related or "").split(".")[0] == "move_id"
                }:
                    pay.move_id.write(move_vals)
        return payments

    def _get_outstanding_account(self, payment_type):
        account_ref = (
            "account_journal_payment_debit_account_id"
            if payment_type == "inbound"
            else "account_journal_payment_credit_account_id"
        )
        chart_template = self.with_context(
            allowed_company_ids=self.company_id.root_id.ids
        ).env["account.chart.template"]
        outstanding_account = (
            chart_template.ref(account_ref, raise_if_not_found=False)
            or self.company_id.transfer_account_id
        )
        if not outstanding_account:
            raise UserError(
                _("No outstanding account could be found to make the payment")
            )
        return outstanding_account

    def write(self, vals):
        if vals.get("state") in ("in_process", "paid") and not vals.get("move_id"):
            self.filtered(lambda p: not p.move_id)._generate_journal_entry()
            self.move_id.filtered(lambda m: m.state == "draft").action_post()

        res = super().write(vals)
        if self.move_id:
            self._synchronize_to_moves(set(vals.keys()))
        return res

    def unlink(self):
        moves = self.move_id
        res = super().unlink()
        moves.filtered(lambda m: m.state != "draft").action_draft()
        moves.unlink()
        return res

    @api.depends("name")
    def _compute_display_name(self):
        for payment in self:
            payment.display_name = payment.name or _("Draft Payment")

    def copy_data(self, default=None):
        default = dict(default or {})
        vals_list = super().copy_data(default)
        for payment, vals in zip(self, vals_list, strict=True):
            vals.update(
                {
                    "journal_id": payment.journal_id.id,
                    "payment_method_line_id": payment.payment_method_line_id.id,
                    **(vals or {}),
                }
            )
        return vals_list

    def _message_mail_after_hook(self, mails):
        for payment, mail in zip(self, mails, strict=False):
            if not payment.message_main_attachment_id and (
                attachments_to_link := mail.attachment_ids.filtered(
                    lambda a: a.res_model == "mail.message"
                )
            ):
                attachments_to_link.write(
                    {"res_model": self._name, "res_id": payment.id}
                )
        return super()._message_mail_after_hook(mails)

    @api.model
    def _reconcile_line_commands(self, lines, line_vals):
        commands = []
        for line, vals in zip_longest(lines, line_vals):
            if line is not None and vals is not None:
                commands.append(Command.update(line.id, vals))
            elif vals is not None:
                commands.append(Command.create(vals))
            else:
                commands.append(Command.delete(line.id))
        return commands

    def _synchronize_to_moves(self, changed_fields):
        if not any(
            field_name in changed_fields
            for field_name in self._get_trigger_fields_to_synchronize()
        ):
            return

        for pay in self:
            if pay.move_id.state == "posted":
                continue
            liquidity_lines, counterpart_lines, writeoff_lines = pay._seek_for_lines()

            if "amount" in changed_fields and len(liquidity_lines) > 1:
                raise UserError(
                    _(
                        "You cannot change the amount of a payment with multiple liquidity lines."
                    )
                )

            write_off_line_vals = []
            if liquidity_lines and counterpart_lines and writeoff_lines:
                write_off_line_vals.append(
                    {
                        "name": writeoff_lines[0].name,
                        "account_id": writeoff_lines[0].account_id.id,
                        "partner_id": writeoff_lines[0].partner_id.id,
                        "currency_id": writeoff_lines[0].currency_id.id,
                        "amount_currency": sum(
                            writeoff_lines.mapped("amount_currency")
                        ),
                        "balance": sum(writeoff_lines.mapped("balance")),
                    }
                )
            line_vals_per_type = pay._prepare_move_lines_per_type(
                write_off_line_vals=write_off_line_vals
            )
            line_ids_commands = [
                *self._reconcile_line_commands(
                    liquidity_lines, line_vals_per_type.get("liquidity_lines", [])
                ),
                *self._reconcile_line_commands(
                    counterpart_lines, line_vals_per_type.get("counterpart_lines", [])
                ),
                *(Command.delete(line.id) for line in writeoff_lines),
                *(
                    Command.create(extra_line_vals)
                    for extra_line_vals in line_vals_per_type.get("write_off_lines", [])
                    + line_vals_per_type.get("withholding_lines", [])
                ),
            ]
            to_write = {
                "date": pay.date,
                "partner_id": pay.partner_id.id,
                "currency_id": pay.currency_id.id,
                "partner_bank_id": pay.partner_bank_id.id,
                "line_ids": line_ids_commands,
            }
            if "journal_id" in changed_fields:
                to_write.update(
                    {
                        "name": "/",
                        "journal_id": pay.journal_id.id,
                    }
                )
            pay.move_id.with_context(skip_invoice_sync=True).write(to_write)

    @api.model
    def _get_trigger_fields_to_synchronize(self):
        return (
            "date",
            "amount",
            "payment_type",
            "partner_type",
            "memo",
            "payment_method_line_id",
            "currency_id",
            "partner_id",
            "destination_account_id",
            "partner_bank_id",
            "journal_id",
        )

    def _generate_journal_entry(
        self, write_off_line_vals=None, force_balance=None, line_ids=None
    ):
        need_move = self.filtered(lambda p: not p.move_id and p.outstanding_account_id)
        assert len(self) == 1 or (
            not write_off_line_vals and not force_balance and not line_ids
        )

        move_vals = [
            pay._generate_move_vals(write_off_line_vals, force_balance, line_ids)
            for pay in need_move
        ]
        moves = self.env["account.move"].create(move_vals)
        for pay, move in zip(need_move, moves, strict=True):
            pay.write({"move_id": move.id, "state": "in_process"})

    def _generate_move_vals(
        self, write_off_line_vals=None, force_balance=None, line_ids=None
    ):
        self.ensure_one()
        return {
            "move_type": "entry",
            "ref": self.memo,
            "date": self.date,
            "journal_id": self.journal_id.id,
            "company_id": self.company_id.id,
            "partner_id": self.partner_id.id,
            "currency_id": self.currency_id.id,
            "partner_bank_id": self.partner_bank_id.id,
            "line_ids": line_ids
            or [
                Command.create(line_vals)
                for line_vals in self._prepare_move_line_default_vals(
                    write_off_line_vals=write_off_line_vals,
                    force_balance=force_balance,
                )
            ],
            "origin_payment_id": self.id,
        }

    def _get_payment_receipt_report_values(self):
        self.ensure_one()
        return {
            "display_invoices": True,
            "display_payment_method": True,
        }

    def mark_as_sent(self):
        self.write({"is_sent": True})

    def unmark_as_sent(self):
        self.write({"is_sent": False})

    def action_post(self):
        for payment in self:
            if (
                payment.require_partner_bank_account
                and not payment.partner_bank_id.allow_out_payment
                and payment.payment_type == "outbound"
            ):
                raise UserError(
                    _(
                        "To record payments with %(method_name)s, the recipient bank account must be manually validated. "
                        "You should go on the partner bank account of %(partner)s in order to validate it.",
                        method_name=payment.payment_method_line_id.name,
                        partner=payment.partner_id.display_name,
                    )
                )
        self.filtered(
            lambda pay: pay.outstanding_account_id.account_type == "asset_cash"
        ).state = "paid"
        self.filtered(
            lambda pay: pay.state in {False, "draft", "in_process"}
        ).state = "in_process"

    def action_validate(self):
        self.state = "paid"

    def action_reject(self):
        self.state = "rejected"

    def action_cancel(self):
        self.state = "canceled"
        draft_moves = self.move_id.filtered(lambda m: m.state == "draft")
        draft_moves.unlink()
        (self.move_id - draft_moves).action_cancel()

    def button_request_cancel(self):
        return self.move_id.button_request_cancel()

    def action_draft(self):
        self.state = "draft"
        self.move_id.action_draft()

    def button_open_invoices(self):
        self.ensure_one()
        return self.reconciled_invoice_ids.with_context(
            create=False
        )._get_records_action(
            name=_("Paid Invoices"),
        )

    def button_open_bills(self):
        self.ensure_one()
        return self.reconciled_bill_ids.with_context(create=False)._get_records_action(
            name=_("Paid Bills"),
        )

    def button_open_statement_lines(self):
        self.ensure_one()
        return self.reconciled_statement_line_ids.with_context(
            create=False
        )._get_records_action(
            name=_("Matched Transactions"),
        )

    def button_open_journal_entry(self):
        self.ensure_one()
        return {
            "name": _("Journal Entry"),
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "context": {"create": False},
            "view_mode": "form",
            "res_id": self.move_id.id,
        }


class AccountMove(models.Model):
    _inherit = "account.move"

    payment_ids = fields.One2many("account.payment", "move_id", string="Payments")
