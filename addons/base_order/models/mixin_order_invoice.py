from itertools import groupby

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Command, Domain
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


class MixinOrderInvoice(models.AbstractModel):
    """Order-level invoice tracking and state computation.

    Uses ``_get_order_type()`` to derive invoice direction (out/in), move
    types, action XML-IDs, and partner payment term fields — eliminating
    the need for per-model overrides of boilerplate routing.

    Requires ``mixin.order`` for ``_get_order_type()``, ``partner_id``,
    ``payment_term_id``, ``state``.  Requires ``line_ids`` from the
    concrete model.
    """

    _name = "mixin.order.invoice"
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
        auxiliary lines remain); ``{done, no}`` is resolved against the
        quantities, since a zero-quantity line is ``no`` forever.
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

        # A line-level ``no`` carries two meanings: "nothing will ever be
        # invoiced" (zero-quantity line) and "nothing to invoice yet"
        # (transferred policy, nothing received). Only the second one keeps an
        # otherwise fully-invoiced order from being ``done``, so orders whose
        # states are exactly {done, no} need one extra lookup to tell the two
        # apart. Kept lazy: it costs nothing on the common cases.
        ambiguous_ids = [
            order._origin.id
            for order in confirmed_orders
            if line_invoice_state_all.get(order._origin.id, set()) == {"done", "no"}
        ]
        pending_no_ids = set()
        if ambiguous_ids:
            pending_no_ids = {
                order.id
                for (order,) in self.env[self._get_line_model()]._read_group(
                    lines_domain
                    + [
                        ("order_id", "in", ambiguous_ids),
                        ("invoice_state", "=", "no"),
                        ("product_qty", "!=", 0),
                    ],
                    ["order_id"],
                )
            }

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
            elif "partial" in states:
                order.invoice_state = "partial"
            elif states == {"done", "no"}:
                # Only pending ``no`` lines (see above) hold the order back;
                # zero-quantity ones never will, so the order is fully invoiced.
                order.invoice_state = (
                    "partial" if order._origin.id in pending_no_ids else "done"
                )
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

        ``name`` is deliberately absent: purchase supplies a literal, while
        sale lets ``_compute_name`` derive it so the section reads in the
        *customer's* language rather than the current user's. Both arrive at
        "Down Payments"; only sale's is translated for the reader.
        """
        self.ensure_one()
        return {
            "order_id": self.id,
            "display_type": "line_section",
            "is_downpayment": True,
            "sequence": self._get_next_line_sequence(),
        }

    def _get_next_line_sequence(self):
        """Sequence placing a new line after every existing one."""
        self.ensure_one()
        return max(self.line_ids.mapped("sequence"), default=9) + 1

    def _get_down_payment_section_line(self):
        """Return this order's down-payment section line, creating it if absent.

        :rtype: recordset of the order line model
        """
        self.ensure_one()
        section = self.line_ids.filtered(
            lambda line: line.display_type and line.is_downpayment,
        )[:1]
        return section or self._create_order_lines(
            [self._prepare_down_payment_line_section_values()],
        )

    def _create_down_payment_lines(self, vals_list):
        """Create down payment lines, sequenced right after their section.

        Sale reached this through two methods a caller had to invoke in order
        (``_create_down_payment_section_line_if_needed`` then
        ``_create_down_payment_lines_from_base_lines``) and purchase through
        one (``_create_downpayments``); the section handling was written twice.
        Callers keep their own vals preparation — sale converts tax base lines,
        purchase is handed vals already — and hand the result here.

        :param list vals_list: creation values, without ``sequence``
        :rtype: recordset of the order line model
        """
        self.ensure_one()
        section = self._get_down_payment_section_line()
        return self._create_order_lines(
            [
                {**vals, "sequence": section.sequence + index}
                for index, vals in enumerate(vals_list, start=1)
            ],
        )

    def _create_order_lines(self, vals_list):
        """Create order lines without recomputing the whole ``line_ids`` o2m.

        The lines already carry ``order_id``, so linking their ids is enough to
        attach them; letting the recordset concatenate instead invalidates the
        one2many and recomputes every line on it.

        ``no_log_for_new_lines`` keeps the chatter quiet: lines created here are
        a side effect of invoicing, not a user edit.

        ``bypass_locked_check`` because the link re-states an attachment the
        ``create`` above already made — it adds nothing a user could see, so it
        must not trip the locked-order guard. Down payments are precisely a flow
        that runs *after* confirmation, and ``_validate_write_locked_order``
        rejects every x2many write on a locked order without inspecting it.
        """
        self.ensure_one()
        lines = (
            self.env[self._get_line_model()]
            .with_context(no_log_for_new_lines=True)
            .create(vals_list)
        )
        self.with_context(bypass_locked_check=True).line_ids = [
            Command.link(line_id) for line_id in lines.ids
        ]
        return lines

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
