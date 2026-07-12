from collections import defaultdict
from itertools import groupby

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Command, Domain
from odoo.libs.numbers.float_utils import float_compare, float_is_zero
from odoo.tools import SQL

INVOICE_STATE = [
    ("no", "Nothing to invoice"),
    ("to do", "To invoice"),
    ("partial", "Partially invoiced"),
    ("done", "Fully invoiced"),
    ("over done", "Over-invoiced"),
]


# ════════════════════════════════════════════════════════════════════
# ORDER-LEVEL INVOICE MIXIN
# ════════════════════════════════════════════════════════════════════


class OrderInvoiceMixin(models.AbstractModel):
    """Order-level invoice tracking and state computation.

    Uses ``_get_order_type()`` to derive invoice direction (out/in), move
    types, action XML-IDs, and partner payment term fields — eliminating
    the need for per-model overrides of boilerplate routing.

    Requires ``order.mixin`` for ``_get_order_type()``, ``partner_id``,
    ``payment_term_id``, ``state``.  Requires ``line_ids`` from the
    concrete model.
    """

    _name = "order.invoice.mixin"
    _description = "Order Invoice Integration"

    # ─── Invoice Tracking Fields ───────────────────────────────────

    invoice_ids = fields.Many2many(
        comodel_name="account.move",
        string="Invoices",
        compute="_compute_invoice_ids",
        search="_search_invoice_ids",
    )
    invoice_count = fields.Integer(
        string="Invoice Count",
        compute="_compute_invoice_ids",
    )
    invoice_state = fields.Selection(
        selection=INVOICE_STATE,
        string="Invoice Status",
        default="no",
        compute="_compute_invoice_state",
        store=True,
        copy=False,
    )

    # ─── Invoice Type Routing ──────────────────────────────────────

    def _get_invoice_move_types(self):
        """Return invoice move_type values for this order type.

        sale → ``('out_invoice', 'out_refund')``,
        purchase → ``('in_invoice', 'in_refund')``.
        """
        direction = "out" if self._get_order_type() == "sale" else "in"
        return (f"{direction}_invoice", f"{direction}_refund")

    # ─── Compute Invoice IDs ──────────────────────────────────────

    @api.depends(
        "line_ids.invoice_line_ids",
        "line_ids.invoice_line_ids.move_id.reversal_move_ids",
    )
    def _compute_invoice_ids(self):
        """Batched 3-step pattern: collect, search orphan refunds, assign.

        Orphan refunds are credit notes created via the "Credit Note" button
        on an invoice — they are not directly linked to order lines.
        """
        move_types = self._get_invoice_move_types()
        refund_type = move_types[1]

        # Step 1: Collect directly linked invoices for all orders
        order_invoices = {}
        all_invoice_ids = set()
        for order in self:
            invoices = order.line_ids.invoice_line_ids.move_id.filtered(
                lambda r: r.move_type in move_types,
            )
            order_invoices[order.id] = set(invoices.ids)
            all_invoice_ids.update(invoices.ids)

        # Step 2: Single batched search for orphan refunds across all orders
        orphan_refunds_by_reversed_id = {}
        if all_invoice_ids:
            orphan_refunds = self.env["account.move"].search(
                [
                    ("reversed_entry_id", "in", list(all_invoice_ids)),
                    ("move_type", "=", refund_type),
                    ("id", "not in", list(all_invoice_ids)),
                ],
            )
            for refund in orphan_refunds:
                orphan_refunds_by_reversed_id.setdefault(
                    refund.reversed_entry_id.id,
                    [],
                ).append(refund.id)

        # Step 3: Assign invoices + orphan refunds to each order
        AccountMove = self.env["account.move"]
        for order in self:
            invoice_ids = order_invoices.get(order.id, set())
            for inv_id in list(invoice_ids):
                if inv_id in orphan_refunds_by_reversed_id:
                    invoice_ids.update(orphan_refunds_by_reversed_id[inv_id])
            # Browse a sorted id list so ``invoice_ids`` has a deterministic
            # order (ascending id = creation order): an invoice precedes the
            # credit notes that later reverse it. Callers rely on this ordering
            # (e.g. ``order.invoice_ids[1]`` to reach a reversal).
            order.invoice_ids = AccountMove.browse(sorted(invoice_ids))
            order.invoice_count = len(invoice_ids)

    def _search_invoice_ids(self, operator, value):
        """Search orders by their invoices.

        The ``in`` operator uses a SQL fast-path whose relation table and
        column names are introspected from the line model's
        ``invoice_line_ids`` field — no per-model override needed.
        """
        if operator in Domain.NEGATIVE_OPERATORS:
            return NotImplemented
        move_types = self._get_invoice_move_types()
        if operator == "in" and value:
            falsy_domain = []
            if False in value:
                # Special case for [('invoice_ids', '=', False)], i.e.
                # "Invoices is not set".  We cannot just search
                # [('line_ids.invoice_line_ids', '=', False)] because it
                # returns orders with at least one uninvoiced line, which is
                # not the same (some lines may have invoices and some don't).
                falsy_domain = [
                    (
                        "line_ids",
                        "not any",
                        [
                            (
                                "invoice_line_ids.move_id.move_type",
                                "in",
                                move_types,
                            ),
                        ],
                    ),
                ]
                if len(value) == 1:
                    return falsy_domain
            line_model = self.env[self._get_line_model()]
            rel_field = line_model._fields["invoice_line_ids"]
            rows = self.env.execute_query(
                SQL(
                    """
                    SELECT array_agg(o.id)
                      FROM %(order_table)s o
                      JOIN %(line_table)s ol ON o.id = ol.order_id
                      JOIN %(rel_table)s rel ON rel.%(rel_line_col)s = ol.id
                      JOIN account_move_line aml ON aml.id = rel.%(rel_move_col)s
                      JOIN account_move am ON am.id = aml.move_id
                     WHERE am.move_type IN %(move_types)s
                       AND am.id = ANY(%(move_ids)s)
                    """,
                    order_table=SQL.identifier(self._table),
                    line_table=SQL.identifier(line_model._table),
                    rel_table=SQL.identifier(rel_field.relation),
                    rel_line_col=SQL.identifier(rel_field.column1),
                    rel_move_col=SQL.identifier(rel_field.column2),
                    move_types=tuple(move_types),
                    # Strip a possible ``False`` sentinel (handled by
                    # falsy_domain) so the SQL array stays int-typed —
                    # ``ANY(ARRAY[False, 5])`` raises a Postgres type error.
                    move_ids=[v for v in value if v is not False],
                ),
            )
            o_ids = rows[0][0] or []
            return [("id", "in", o_ids)] + falsy_domain
        return [
            (
                "line_ids.invoice_line_ids",
                "any",
                [
                    ("move_id.move_type", "in", move_types),
                    ("move_id", operator, value),
                ],
            ),
        ]

    # ─── Compute Invoice State ─────────────────────────────────────

    @api.depends("state", "line_ids.invoice_state", "invoice_ids")
    def _compute_invoice_state(self):
        """Batched computation using ``_read_group`` over line invoice states.

        Priority: ``over done`` > ``to do`` > ``partial`` > ``done`` > ``no``.
        The ``to do`` resolution is delegated to
        ``_resolve_invoice_state_to_do()`` (sale downgrades to ``no`` when only
        auxiliary lines remain).
        """
        confirmed_orders = self.filtered(lambda o: o.state == "done")
        (self - confirmed_orders).invoice_state = "no"
        if not confirmed_orders:
            return

        # Batched: single _read_group query for all confirmed orders
        lines_domain = [
            ("is_downpayment", "=", False),
            ("display_type", "=", False),
        ]
        line_invoice_state_all = {}
        for order, invoice_state in self.env[self._get_line_model()]._read_group(
            lines_domain + [("order_id", "in", confirmed_orders._origin.ids)],
            ["order_id", "invoice_state"],
        ):
            line_invoice_state_all.setdefault(order.id, set()).add(invoice_state)

        for order in confirmed_orders:
            states = line_invoice_state_all.get(order._origin.id, set())
            if not states:
                order.invoice_state = "no"
                continue
            # Single state → direct assignment (common case optimization)
            if len(states) == 1:
                order.invoice_state = next(iter(states))
                continue
            # Multiple states → resolve by priority
            if "over done" in states:
                order.invoice_state = "over done"
            elif "to do" in states:
                order.invoice_state = order._resolve_invoice_state_to_do(
                    states,
                    lines_domain,
                )
            elif "partial" in states or states == {"done", "no"}:
                order.invoice_state = "partial"
            else:
                order.invoice_state = "no"

    def _resolve_invoice_state_to_do(self, states, lines_domain):
        """Resolve the order invoice state when at least one line is ``to do``.

        Sale overrides to downgrade to ``no`` when the only lines left to
        invoice cannot be invoiced alone (e.g. discount lines).

        :param set states: distinct line invoice states for this order
        :param list lines_domain: domain filtering the relevant order lines
        :rtype: str
        """
        self.ensure_one()
        return "to do"

    # ─── Invoice Action ────────────────────────────────────────────

    @api.readonly
    def action_view_invoice(self, invoices=False):
        """Open the invoice/bill list or form view.

        Uses ``_get_order_type()`` to derive the action XML-ID and
        default move type.  Hook: ``_get_invoice_action_context()``
        for model-specific context values.
        """
        if not invoices:
            invoices = self.mapped("invoice_ids")

        direction = "out" if self._get_order_type() == "sale" else "in"
        action = self.env["ir.actions.actions"]._for_xml_id(
            f"account.action_move_{direction}_invoice_type",
        )

        if len(invoices) > 1:
            action["domain"] = [("id", "in", invoices.ids)]
        elif len(invoices) == 1:
            form_view = [(self.env.ref("account.view_move_form").id, "form")]
            if "views" in action:
                action["views"] = form_view + [
                    (state, view) for state, view in action["views"] if view != "form"
                ]
            else:
                action["views"] = form_view
            action["res_id"] = invoices.id
        else:
            action = {"type": "ir.actions.act_window_close"}

        context = {"default_move_type": f"{direction}_invoice"}
        if len(self) == 1:
            context.update(self._get_invoice_action_context())
        action["context"] = context
        return action

    def _get_invoice_action_context(self):
        """Hook for model-specific invoice action context.

        Base provides partner and payment term (routed by order type).
        Sale overrides to add ``partner_shipping_id``.
        Purchase overrides to add ``invoice_origin``.
        """
        self.ensure_one()
        pt_field = self._get_partner_payment_term_field()
        return {
            "default_partner_id": self.partner_id.id,
            "default_invoice_payment_term_id": (
                self.payment_term_id.id
                or self.partner_id[pt_field].id
                or self.env["account.move"]
                .default_get(["invoice_payment_term_id"])
                .get("invoice_payment_term_id")
            ),
        }

    # ─── Invoice Grouping & Preparation ─────────────────────────────

    def _get_invoice_grouping_keys(self):
        """Return field names used to group orders into a single invoice.

        Sale overrides to add ``partner_shipping_id``.
        """
        return ["company_id", "partner_id", "currency_id", "fiscal_position_id"]

    def _get_invoice_partner(self):
        """Return the partner to invoice.

        Sale: ``partner_invoice_id``; purchase: the invoice address.
        """
        self.ensure_one()
        return self.partner_id

    def _prepare_invoice_vals(self):
        """Prepare the base dict for creating an invoice from this order.

        Child models call ``super()`` and extend with model-specific values
        (UTM fields, partner_bank, transaction_ids, etc.).
        """
        self.ensure_one()
        direction = "out" if self._get_order_type() == "sale" else "in"
        move_type = self.env.context.get("default_move_type", f"{direction}_invoice")
        invoice_partner = self._get_invoice_partner()
        values = {
            "company_id": self.company_id.id,
            "currency_id": self.currency_id.id,
            "partner_id": invoice_partner.id,
            "invoice_payment_term_id": self.payment_term_id.id,
            "fiscal_position_id": (
                self.fiscal_position_id
                or self.fiscal_position_id._get_fiscal_position(invoice_partner)
            ).id,
            "invoice_user_id": self.user_id.id,
            "move_type": move_type,
            "narration": self.notes,
            "invoice_origin": self.name,
            "invoice_line_ids": [],
        }
        if self.journal_id:
            values["journal_id"] = self.journal_id.id
        return values

    # ─── Invoice Creation ──────────────────────────────────────────

    def _create_invoices(self, grouped=False, final=False, date=None):
        """Create invoice(s)/bill(s) for the orders in ``self``.

        Shared 4-phase pipeline: build per-order values, group them, create the
        moves, and flip negative-total moves to refunds.  The divergent parts
        (invoiceable-line selection, down-payment sections, post-processing) are
        hooks.

        :param bool grouped: keep one invoice per order instead of grouping.
        :param bool final: generate refunds where needed.
        :rtype: account.move recordset
        """
        if not self.env["account.move"].has_access("create"):
            try:
                self.check_access("write")
            except AccessError:
                return self.env["account.move"]

        # 1) Build per-order invoice values.
        invoice_vals_list = []
        sequence = self._get_invoice_line_sequence_start()
        for order in self:
            order = order._get_invoicing_order()
            invoice_vals = order._prepare_invoice_vals()
            line_commands, sequence = order._prepare_invoice_line_commands(
                order._get_invoiceable_lines(final),
                sequence,
            )
            if not line_commands:
                continue
            invoice_vals["invoice_line_ids"] += line_commands
            invoice_vals_list.append(invoice_vals)

        if not invoice_vals_list:
            if self.env.context.get("raise_if_nothing_to_invoice", True):
                raise UserError(self._nothing_to_invoice_error_message())
            return self.env["account.move"]

        # 2) Group values by the grouping keys.
        if not grouped:
            invoice_vals_list = self._group_invoice_vals(invoice_vals_list)
        invoice_vals_list = self._post_group_invoice_vals(invoice_vals_list)

        # 3) Create the moves under the right move type.
        moves = self._create_invoice_moves(invoice_vals_list)

        # 4) Some moves might be refunds: switch negative-total moves.
        self._switch_negative_moves(moves, final)

        self._post_create_invoices(moves)
        return moves

    def _get_invoicing_order(self):
        """Return ``self`` with the context used to build its invoice values.

        Sale additionally switches to the invoice partner's language.
        """
        self.ensure_one()
        return self.with_company(self.company_id)

    def _get_invoice_line_sequence_start(self):
        """First ``sequence`` assigned to generated invoice lines.

        Purchase numbers bill lines from 10; sale numbers invoice lines
        from 0 (and has tests pinning the absolute values).
        """
        return 10

    def _post_group_invoice_vals(self, invoice_vals_list):
        """Adjust the grouped invoice values before creating the moves.

        Sale resequences lines when several orders were merged into one
        invoice.  Base: no-op.
        """
        return invoice_vals_list

    def _create_invoice_moves(self, invoice_vals_list):
        """Create the account moves from the prepared values.

        Base (sale's behaviour): sudo batch create so a salesperson can
        invoice without billing rights.  Purchase overrides with a plain
        per-company create.
        """
        invoice_type = self._get_invoice_move_types()[0]
        return (
            self.env["account.move"]
            .sudo()
            .with_context(default_move_type=invoice_type)
            .create(invoice_vals_list)
        )

    def _switch_negative_moves(self, moves, final):
        """Switch negative-total moves to refunds.

        Base (purchase's behaviour): unconditional.  Sale gates on ``final``
        and protects ``team_id`` recomputation.
        """
        moves_to_switch = moves.sudo().filtered(
            lambda m: m.currency_id.round(m.amount_total) < 0,
        )
        if moves_to_switch:
            moves_to_switch.action_switch_move_type()

    def _get_invoiceable_lines(self, final=False):
        """Lines to invoice for this order (override for sections/down payments)."""
        self.ensure_one()
        return self.line_ids.filtered(
            lambda line: not line.display_type and line.qty_to_invoice,
        )

    def _prepare_down_payment_line_section_values(self):
        """Values for the order-line section grouping down payment lines.

        Common subset of sale and purchase.  Purchase extends with ``name``
        and a ``sequence`` after the last line; sale's caller supplies the
        ``sequence`` itself.
        """
        self.ensure_one()
        return {
            "order_id": self.id,
            "display_type": "line_section",
            "is_downpayment": True,
        }

    def _prepare_invoice_line_commands(self, invoiceable_lines, sequence=10):
        """Build the ``invoice_line_ids`` commands for one order.

        :return: ``([Command.create(vals), ...], next_sequence)``
        """
        commands = []
        for line in invoiceable_lines:
            commands.extend(
                Command.create(vals)
                for vals in line._prepare_aml_vals_list(sequence=sequence)
            )
            sequence += 1
        return commands, sequence

    def _group_invoice_vals(self, invoice_vals_list):
        """Group per-order invoice values by ``_get_invoice_grouping_keys``."""
        grouping_keys = self._get_invoice_grouping_keys()

        def key(vals):
            return [vals.get(k) for k in grouping_keys]

        grouped = []
        for _keys, group in groupby(sorted(invoice_vals_list, key=key), key=key):
            origins = set()
            ref_vals = None
            for vals in group:
                if not ref_vals:
                    ref_vals = vals
                else:
                    ref_vals["invoice_line_ids"] += vals["invoice_line_ids"]
                origins.add(vals.get("invoice_origin"))
            ref_vals["invoice_origin"] = ", ".join(sorted(o for o in origins if o))
            grouped.append(ref_vals)
        return grouped

    def _post_create_invoices(self, moves):
        """Hook after invoices are created (sale links origins, purchase files)."""
        return moves

    def _nothing_to_invoice_error_message(self):
        """Error raised when there is nothing to invoice."""
        return _("There is nothing to invoice for this order.")


# ════════════════════════════════════════════════════════════════════
# LINE-LEVEL INVOICE MIXIN
# ════════════════════════════════════════════════════════════════════


class OrderLineInvoiceMixin(models.AbstractModel):
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

    _name = "order.line.invoice.mixin"
    _description = "Order Line Invoice Integration"

    # ─── Currency (required for Monetary fields) ───────────────────

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
    @api.depends("price_unit", "qty_invoiced_at_date", "qty_transferred_at_date")
    def _compute_amount_to_invoice_at_date(self):
        for line in self:
            line.amount_to_invoice_at_date = (
                line.qty_transferred_at_date - line.qty_invoiced_at_date
            ) * line.price_unit

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
                    line.qty_transferred if policy == "transferred" else line.product_qty
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

    def _prepare_aml_vals_list(self, **optional_values):
        """Prepare the list of values to create invoice lines.

        Delegates to ``_prepare_aml_vals()``, which is model-specific.
        Override to return multiple dicts (e.g. for combo product expansion).

        :param optional_values: parameters added to the returned invoice lines
        :rtype: list[dict]
        """
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
