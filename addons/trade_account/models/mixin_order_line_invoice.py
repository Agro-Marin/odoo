from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.libs.debug_log import DebugLog
from odoo.libs.numbers import float_compare, float_is_zero

from .mixin_order_invoice import INVOICE_STATE
from odoo.addons.trade.tools import TradeDirection, direction_of

_debug = DebugLog(__name__)


class MixinOrderLineInvoice(models.AbstractModel):
    _name = "mixin.order.line.invoice"
    _description = "Order Line Invoice Integration"
    _direction: TradeDirection | None = None

    currency_id = fields.Many2one(comodel_name="res.currency")

    invoice_line_ids = fields.Many2many(
        comodel_name="account.move.line",
        string="Invoice Lines",
        copy=False,
    )

    qty_invoiced = fields.Float(
        string="Invoiced Quantity",
        digits="Product Unit",
        compute="_compute_invoice_amounts",
        store=True,
    )
    qty_to_invoice = fields.Float(
        string="Quantity To Invoice",
        digits="Product Unit",
        compute="_compute_invoice_amounts",
        store=True,
    )
    qty_invoiced_at_date = fields.Float(
        string="Invoiced",
        digits="Product Unit",
        compute="_compute_qty_invoiced_at_date",
    )

    amount_taxexc_invoiced = fields.Monetary(
        string="Untaxed Invoiced Amount",
        compute="_compute_invoice_amounts",
        store=True,
    )
    amount_taxinc_invoiced = fields.Monetary(
        string="Invoiced Amount",
        compute="_compute_invoice_amounts",
        store=True,
    )
    amount_taxexc_to_invoice = fields.Monetary(
        string="Untaxed Amount To Invoice",
        compute="_compute_invoice_amounts",
        store=True,
    )
    amount_taxinc_to_invoice = fields.Monetary(
        string="Un-invoiced Balance",
        compute="_compute_invoice_amounts",
        store=True,
    )
    amount_to_invoice_at_date = fields.Float(
        string="Amount",
        compute="_compute_amount_to_invoice_at_date",
    )

    invoice_state = fields.Selection(
        selection=INVOICE_STATE,
        string="Invoice Status",
        compute="_compute_invoice_state",
        default="no",
        store=True,
    )

    def _get_invoice_move_types(self):
        return direction_of(self).move_types

    def _get_invoice_lines(self):
        self.check_singleton()
        if self.env.context.get("accrual_entry_date"):
            accrual_date = fields.Date.from_string(
                self.env.context["accrual_entry_date"],
            )
            _debug.logic("invoice_lines", line=self, by="accrual_entry_date")
            return self.invoice_line_ids.filtered(
                lambda l: (
                    l.move_id.invoice_date and l.move_id.invoice_date <= accrual_date
                ),
            )
        return self.invoice_line_ids

    def _get_posted_invoice_lines(self):
        self.check_singleton()
        return self._get_invoice_lines().filtered(
            lambda l: (
                l.parent_state == "posted"
                or l.move_id.payment_state == "invoicing_legacy"
            )
        )

    def _get_open_invoice_lines(self):
        # A draft invoice already claims its quantity: counting only posted
        # ones lets the same line be invoiced twice. Amounts stay posted-only.
        self.check_singleton()
        return self._get_invoice_lines().filtered(
            lambda l: (
                l.parent_state != "cancel"
                or l.move_id.payment_state == "invoicing_legacy"
            )
        )

    def _prepare_qty_invoiced(self):
        invoiced_qties = defaultdict(float)
        invoice_type, refund_type = self._get_invoice_move_types()
        for line in self:
            for inv_line in line._get_open_invoice_lines():
                qty = inv_line.product_uom_id._get_quantity_in_unit(
                    inv_line.quantity,
                    line.product_uom_id,
                )
                if inv_line.move_id.move_type == invoice_type:
                    invoiced_qties[line] += qty
                elif inv_line.move_id.move_type == refund_type:
                    invoiced_qties[line] -= qty
        return invoiced_qties

    @api.depends_context("accrual_entry_date")
    @api.depends("qty_invoiced")
    def _compute_qty_invoiced_at_date(self):
        if not self._date_in_the_past():
            _debug.logic("qty_invoiced_at_date", lines=self, by="current_quantity")
            for line in self:
                line.qty_invoiced_at_date = line.qty_invoiced
            return
        invoiced_quantities = self._prepare_qty_invoiced()
        for line in self:
            line.qty_invoiced_at_date = invoiced_quantities[line]

    @api.depends_context("accrual_entry_date")
    @api.depends(
        "price_unit",
        "discount",
        "qty_invoiced_at_date",
        "qty_transferred_at_date",
        "tax_ids",
        "product_qty",
        "product_uom_id",
    )
    def _compute_amount_to_invoice_at_date(self):
        for line in self:
            line.amount_to_invoice_at_date = (
                line.qty_transferred_at_date - line.qty_invoiced_at_date
            ) * line._get_price_unit_gross()

    def _compute_invoice_amounts(self):
        _debug.logic("invoice_amounts_not_implemented", model=self._name)
        raise NotImplementedError(
            f"{self._name} must implement _compute_invoice_amounts()"
        )

    def _compute_invoice_state(self):
        precision = self.env["decimal.precision"].get_precision("Product Unit")
        policy_field = direction_of(self).invoice_policy_field
        _debug.perf.count("line_invoice_state", lines=len(self), policy=policy_field)
        for line in self.filtered(lambda l: not l.display_type):
            policy = line.product_id[policy_field]

            if line.is_downpayment:
                if line.currency_id.is_zero(line.amount_taxexc_to_invoice):
                    line.invoice_state = "done"
                else:
                    line.invoice_state = "to do"
                continue

            if float_is_zero(line.product_qty, precision_digits=precision):
                line.invoice_state = "no"

            elif not float_is_zero(line.qty_to_invoice, precision_digits=precision):
                if line.qty_to_invoice < 0:
                    if policy == "ordered":
                        line.invoice_state = "over done"
                    else:
                        line.invoice_state = "to do"
                elif float_is_zero(line.qty_invoiced, precision_digits=precision):
                    line.invoice_state = "to do"
                else:
                    line.invoice_state = "partial"

            elif float_is_zero(line.qty_to_invoice, precision_digits=precision):
                qty_to_compare = (
                    line.qty_transferred
                    if policy == "transferred"
                    else line.product_qty
                )
                if (
                    policy == "transferred"
                    and float_is_zero(line.qty_transferred, precision_digits=precision)
                    and float_is_zero(line.qty_invoiced, precision_digits=precision)
                ):
                    line.invoice_state = "no"
                    continue
                compare = float_compare(
                    line.qty_invoiced, qty_to_compare, precision_digits=precision
                )
                if compare == 0:
                    line.invoice_state = "done"
                elif compare > 0:
                    if policy == "transferred":
                        line.invoice_state = "to do"
                    else:
                        line.invoice_state = "over done"
                else:
                    line.invoice_state = "no"

    def _assert_invoiced_uom_convertible(self):
        for line in self.filtered(lambda l: not l.display_type):
            target_uom = line.product_uom_id
            if not target_uom:
                continue
            for inv_line in line._get_posted_invoice_lines():
                source_uom = inv_line.product_uom_id
                if not source_uom or not inv_line.quantity:
                    continue
                if not source_uom._has_common_reference(target_uom):
                    _debug.logic(
                        "invoiced_uom_not_convertible",
                        line=line,
                        source=source_uom,
                        target=target_uom,
                    )
                    raise UserError(
                        self.env._(
                            "Cannot invoice “%(line)s”: its already-invoiced "
                            "quantity is recorded in %(source)s, which cannot "
                            "be converted into %(target)s. Align the units of "
                            "measure on the order line and its invoice lines, "
                            "then try again.",
                            line=line.display_name,
                            source=source_uom.display_name,
                            target=target_uom.display_name,
                        )
                    )

    def _prepare_aml_vals_list(self, **optional_values):
        self._assert_transferred_uom_convertible()
        self._assert_invoiced_uom_convertible()
        return [self._prepare_aml_vals(**optional_values)]

    def _is_invoiceable(self, final=False):
        self.check_singleton()
        if self.display_type == "line_note":
            return True
        precision = self.env["decimal.precision"].get_precision("Product Unit")
        return not float_is_zero(self.qty_to_invoice, precision_digits=precision)

    def _prepare_down_payment_deduction_aml_vals(self):
        return {"quantity": -1.0}

    def _prepare_aml_vals(self, **optional_values):
        self.check_singleton()
        move = optional_values.pop("move", None)
        refund_type = self._get_invoice_move_types()[1]
        res = {
            "display_type": self.display_type or "product",
            "name": self.env["account.move.line"]._get_journal_items_full_name(
                self.name,
                self.product_id.display_name,
            ),
            "product_id": self.product_id.id,
            "product_uom_id": self.product_uom_id.id,
            "quantity": (
                -self.qty_to_invoice
                if move and move.move_type == refund_type
                else self.qty_to_invoice
            ),
            "discount": self.discount,
            "price_unit": self.currency_id._convert(
                self.price_unit,
                (move and move.currency_id) or self.currency_id,
                self.company_id,
                (move and move.date) or fields.Date.today(),
                round=False,
            ),
            "tax_ids": [Command.set(self.tax_ids.ids)],
            "is_downpayment": self.is_downpayment,
        }
        link_field = self._get_invoice_line_link_field()
        if link_field:
            res[link_field] = [Command.link(self.id)]
        if self.is_downpayment and (
            downpayment_lines := self.invoice_line_ids.filtered("is_downpayment")
        ):
            res["account_id"] = downpayment_lines.account_id[:1].id
            _debug.logic("aml_account_from_downpayment", line=self)
        res.update(optional_values)
        if self.display_type:
            res["account_id"] = False
        _debug.pipeline("aml_vals", line=self, quantity=res["quantity"])
        return res

    def _get_invoice_line_link_field(self):
        return

    def _get_price_unit_gross(self):
        self.check_singleton()
        price_unit = self.price_unit
        if self.discount:
            price_unit *= 1 - self.discount / 100
        if self.tax_ids:
            qty = self.product_qty or 1
            price_unit = self.tax_ids.compute_all(
                price_unit,
                currency=self.order_id.currency_id,
                quantity=qty,
                rounding_method="round_globally",
            )["total_void"]
            price_unit /= qty
        if self.product_uom_id.id != self.product_id.uom_id.id:
            price_unit = self.product_uom_id._get_price_in_unit(
                price_unit, self.product_id.uom_id
            )
        return price_unit

    @api.depends("product_id", "product_uom_id", "product_qty", "display_type")
    def _is_invoiced_on_transferred(self):
        return False

    def _assert_transferred_uom_convertible(self):
        for line in self.filtered(lambda l: l._is_invoiced_on_transferred()):
            try:
                line.with_context(uom_reconcile_strict=True)._prepare_qty_transferred()
            except UserError as error:
                _debug.logic(
                    "transferred_uom_not_convertible",
                    line=line,
                    uom=line.product_uom_id,
                )
                raise UserError(
                    self.env._(
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
