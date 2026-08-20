from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.libs.numbers import float_compare, float_is_zero

from .mixin_order_invoice import INVOICE_STATE

# ════════════════════════════════════════════════════════════════════
# ORDER-LEVEL INVOICE MIXIN
# ════════════════════════════════════════════════════════════════════


class MixinOrderLineInvoice(models.AbstractModel):
    """Line-level invoice tracking fields and shared helpers.

    Provides:
    - Invoice line tracking (``invoice_line_ids``)
    - Quantity and amount fields (``qty_invoiced``, ``amount_taxexc_invoiced``, ...)
    - Shared helpers (``_get_invoice_lines()``, ``_get_posted_invoice_lines()``)

    The compute methods ``_compute_invoice_amounts()`` and
    ``_compute_invoice_state()`` are **stubs** — implementations differ
    too much between sale and purchase to unify cleanly (combo products,
    direction sign, policy fields, over-invoicing semantics).

    Requires ``order_id``, ``company_id``, ``currency_id``, ``product_uom_id``
    and ``_get_order_type()`` from the concrete model / companion mixins.
    """

    _name = "mixin.order.line.invoice"
    _description = "Order Line Invoice Integration"

    # ─── Currency (required for Monetary fields) ───────────────────
    # Structural, not composition-defensive: this abstract mixin owns Monetary
    # fields whose ``currency_field`` must resolve on the mixin itself at
    # registry setup. Concrete models also inherit ``currency_id`` from
    # ``mixin.order``, but the mixin must still declare its own. Do not remove.

    currency_id = fields.Many2one("res.currency")

    # ─── Invoice Line Tracking ─────────────────────────────────────

    invoice_line_ids = fields.Many2many(
        comodel_name="account.move.line",
        string="Invoice Lines",
        copy=False,
    )

    # ─── Quantity Fields ───────────────────────────────────────────

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
    # Same as `qty_invoiced` but non-stored and depending on the context.
    qty_invoiced_at_date = fields.Float(
        string="Invoiced",
        digits="Product Unit",
        compute="_compute_qty_invoiced_at_date",
    )

    # ─── Invoice Amount Fields ─────────────────────────────────────

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

    # ─── Invoice State ─────────────────────────────────────────────

    invoice_state = fields.Selection(
        selection=INVOICE_STATE,
        string="Invoice Status",
        default="no",
        compute="_compute_invoice_state",
        store=True,
    )

    # ─── Routing ───────────────────────────────────────────────────

    def _get_invoice_move_types(self):
        """Return ``(invoice, refund)`` move types for this order type."""
        direction = "out" if self._get_order_type() == "sale" else "in"
        return (f"{direction}_invoice", f"{direction}_refund")

    def _get_invoice_policy_field(self):
        """Return the product field name for invoice/bill policy.

        sale → ``'invoice_policy'``, purchase → ``'bill_policy'``.
        """
        if self._get_order_type() == "sale":
            return "invoice_policy"
        return "bill_policy"

    # ─── Shared Helpers ────────────────────────────────────────────

    def _get_invoice_lines(self):
        """Return invoice lines, filtered by accrual date if in context."""
        self.ensure_one()
        if self.env.context.get("accrual_entry_date"):
            accrual_date = fields.Date.from_string(
                self.env.context["accrual_entry_date"],
            )
            return self.invoice_line_ids.filtered(
                lambda l: (
                    l.move_id.invoice_date and l.move_id.invoice_date <= accrual_date
                ),
            )
        return self.invoice_line_ids

    def _get_posted_invoice_lines(self):
        """Return posted invoice lines for this order line.

        Filters to posted invoices and ``invoicing_legacy`` payment state.
        """
        self.ensure_one()
        return self._get_invoice_lines().filtered(
            lambda l: (
                l.parent_state == "posted"
                or l.move_id.payment_state == "invoicing_legacy"
            )
        )

    def _prepare_qty_invoiced(self):
        """Return the signed invoiced quantity per line (invoices - refunds).

        :rtype: dict
        """
        invoiced_qties = defaultdict(float)
        invoice_type, refund_type = self._get_invoice_move_types()
        for line in self:
            for inv_line in line._get_invoice_lines():
                if (
                    inv_line.move_id.state != "cancel"
                    or inv_line.move_id.payment_state == "invoicing_legacy"
                ):
                    qty = inv_line.product_uom_id._compute_quantity(
                        inv_line.quantity,
                        line.product_uom_id,
                    )
                    if inv_line.move_id.move_type == invoice_type:
                        invoiced_qties[line] += qty
                    elif inv_line.move_id.move_type == refund_type:
                        invoiced_qties[line] -= qty
        return invoiced_qties

    # ─── At-Date Computes ──────────────────────────────────────────

    @api.depends_context("accrual_entry_date")
    @api.depends("qty_invoiced")
    def _compute_qty_invoiced_at_date(self):
        if not self._date_in_the_past():
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
        """Value still to invoice at the accrual date.

        Uses ``_get_price_unit_gross()`` (mixin.order.line.amount), not the raw
        ``price_unit``: the accrued amount must net out the discount, strip
        included taxes and convert to the product's reference UoM. sale and
        purchase both carried this exact override; the raw ``price_unit`` left
        here was wrong for any other consumer of the mixin.
        """
        for line in self:
            line.amount_to_invoice_at_date = (
                line.qty_transferred_at_date - line.qty_invoiced_at_date
            ) * line._get_price_unit_gross()

    # ─── Compute Stubs (concrete models must override) ─────────────

    def _compute_invoice_amounts(self):
        """Compute invoice quantities and amounts for each line.

        Implementations differ too much to unify:

        - **Sale**: monolithic with combo product post-processing,
          ``direction_sign = -move.direction_sign``
        - **Purchase**: decomposed into helpers
          (``_sum_invoiced_amounts``, ``_compute_to_invoice_amounts``),
          ``direction_sign = +move.direction_sign``

        Concrete models must override entirely with their own
        ``@api.depends`` decorator.
        """
        raise NotImplementedError(
            f"{self._name} must implement _compute_invoice_amounts()"
        )

    def _compute_invoice_state(self):
        """Compute the per-line invoice state (shared sale/purchase logic).

        Keyed on the product's invoice/bill policy via
        ``_get_invoice_policy_field()`` ('ordered' vs 'transferred'). Concrete
        models override only to declare their own ``@api.depends`` (the policy
        field name differs) and call ``super()``.

        States:

        - no: nothing to invoice (zero qty, or not-yet-received transferred line).
        - to do: quantity left to invoice with nothing invoiced yet, or a credit
          note is needed on a 'transferred' line (invoiced more than received).
        - partial: quantity left to invoice AND some already invoiced.
        - done: fully invoiced (qty_invoiced == the invoiceable quantity).
        - over done: over-invoiced on an 'ordered' line (qty_invoiced > product_qty).
        """
        precision = self.env["decimal.precision"].precision_get("Product Unit")
        policy_field = self._get_invoice_policy_field()
        for line in self.filtered(lambda l: not l.display_type):
            policy = line.product_id[policy_field]

            # Downpayment lines: state follows the remaining amount to invoice.
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
                    # Invoiced more than due: genuine over-invoice on 'ordered';
                    # on 'transferred' a return happened -> credit note ('to do').
                    if policy == "ordered":
                        line.invoice_state = "over done"
                    else:
                        line.invoice_state = "to do"
                elif float_is_zero(line.qty_invoiced, precision_digits=precision):
                    # Nothing invoiced yet, positive qty to invoice
                    line.invoice_state = "to do"
                else:
                    # Some quantity already invoiced, more to invoice
                    line.invoice_state = "partial"

            elif float_is_zero(line.qty_to_invoice, precision_digits=precision):
                # 'transferred' compares to qty received; 'ordered' to qty ordered.
                qty_to_compare = (
                    line.qty_transferred
                    if policy == "transferred"
                    else line.product_qty
                )
                # transferred, nothing received and nothing invoiced -> nothing yet.
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
                    # Over-invoiced vs the basis.
                    if policy == "transferred":
                        line.invoice_state = "to do"
                    else:
                        line.invoice_state = "over done"
                else:
                    line.invoice_state = "no"

    # ─── Invoice Line Preparation ──────────────────────────────────

    def _assert_invoiced_uom_convertible(self):
        """Posting-boundary guard for the leniently-computed invoiced qty.

        Checks the conversions ``_compute_invoice_amounts`` performs without
        running it: that compute writes six stored fields, and a validation
        must not have side effects on the values it is about to protect.

        :raises UserError: when an invoice-line UoM cannot be converted into
            the order-line UoM.
        """
        # No `_invoiced_on_transferred()` filter: this conversion runs for
        # every invoiced line, whatever its invoicing policy.  Empty UoM and
        # zero quantity are skipped because `_compute_quantity` returns early
        # on both, so raising here would be stricter than the compute.
        for line in self.filtered(lambda l: not l.display_type):
            target_uom = line.product_uom_id
            if not target_uom:
                continue
            for inv_line in line._get_posted_invoice_lines():
                source_uom = inv_line.product_uom_id
                if not source_uom or not inv_line.quantity:
                    continue
                if not source_uom._has_common_reference(target_uom):
                    raise UserError(
                        _(
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
        """Prepare the list of values to create invoice lines.

        Delegates to ``_prepare_aml_vals()``, which is model-specific.
        Override to return multiple dicts (e.g. for combo product expansion).

        :param optional_values: parameters added to the returned invoice lines
        :rtype: list[dict]
        """
        self._assert_transferred_uom_convertible()
        self._assert_invoiced_uom_convertible()
        return [self._prepare_aml_vals(**optional_values)]

    def _prepare_aml_vals(self, **optional_values):
        """Prepare the values for one invoice line from this order line.

        Builds the shared ``account.move.line`` dict.  Model-specific extras
        (sale: combo section, ``extra_tax_data``; purchase: currency conversion,
        refund quantity sign) are added by ``super()``-extending overrides.

        :param optional_values: extra values merged into the returned dict
        :rtype: dict
        """
        self.ensure_one()
        res = {
            "display_type": self.display_type or "product",
            "name": self.env["account.move.line"]._get_journal_items_full_name(
                self.name,
                self.product_id.display_name,
            ),
            "product_id": self.product_id.id,
            "product_uom_id": self.product_uom_id.id,
            "quantity": self.qty_to_invoice,
            "discount": self.discount,
            "price_unit": self.price_unit,
            "tax_ids": [Command.set(self.tax_ids.ids)],
            "is_downpayment": self.is_downpayment,
        }
        link_field = self._get_invoice_line_link_field()
        if link_field:
            res[link_field] = [Command.link(self.id)]
        if self.is_downpayment and self.invoice_line_ids:
            res["account_id"] = self.invoice_line_ids.account_id[:1].id
        res.update(optional_values)
        return res

    def _get_invoice_line_link_field(self):
        """Order-line link field on ``account.move.line``.

        Sale → ``'sale_line_ids'``, purchase → ``'purchase_line_ids'``.
        """
        return
