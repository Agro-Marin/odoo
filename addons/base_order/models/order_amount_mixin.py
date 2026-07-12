from odoo import api, fields, models


class OrderAmountMixin(models.AbstractModel):
    """Order-level amount computation and tax totals.

    Consolidates the tax computation pattern that is identical in sale.order
    and purchase.order — both delegate to ``account.tax._get_tax_totals_summary()``
    via a shared helper ``_build_tax_totals_data()``.

    Hook: ``_get_additional_base_lines()`` — returns ``[]`` by default.
    Sale overrides to add early payment discount lines.

    Requires ``order.mixin`` fields: ``currency_id``, ``company_id``,
    ``payment_term_id``, ``currency_rate``.  Requires ``line_ids`` from the
    concrete model.
    """

    _name = "order.amount.mixin"
    _description = "Order Amount Computation"

    # ─── Currency (required for Monetary fields) ───────────────────
    # Structural, not composition-defensive: this abstract mixin owns Monetary
    # fields whose ``currency_field`` must resolve on the mixin itself at
    # registry setup. Concrete models also inherit ``currency_id`` from
    # ``order.mixin``, but the mixin must still declare its own. Do not remove.

    currency_id = fields.Many2one("res.currency")

    # ─── Amount Fields ─────────────────────────────────────────────

    amount_untaxed = fields.Monetary(
        string="Untaxed Amount",
        compute="_compute_amounts",
        store=True,
        tracking=True,
    )
    amount_tax = fields.Monetary(
        string="Taxes",
        compute="_compute_amounts",
        store=True,
        tracking=True,
    )
    amount_total = fields.Monetary(
        string="Total",
        compute="_compute_amounts",
        store=True,
        tracking=True,
    )
    tax_totals = fields.Binary(
        compute="_compute_tax_totals",
        exportable=False,
    )

    # ─── Invoice Amount Fields (order-level sums) ──────────────────

    amount_taxexc_invoiced = fields.Monetary(
        string="Already Invoiced (Tax Excl.)",
        compute="_compute_amounts_invoice",
    )
    amount_taxinc_invoiced = fields.Monetary(
        string="Already Invoiced (Tax Incl.)",
        compute="_compute_amounts_invoice",
    )
    amount_taxexc_to_invoice = fields.Monetary(
        string="Un-invoiced Balance (Tax Excl.)",
        compute="_compute_amounts_invoice",
    )
    amount_taxinc_to_invoice = fields.Monetary(
        string="Un-invoiced Balance (Tax Incl.)",
        compute="_compute_amounts_invoice",
    )

    # ─── Credit Warning ────────────────────────────────────────────

    partner_credit_warning = fields.Text(
        compute="_compute_partner_credit_warning",
    )

    # ─── Tax Computation ───────────────────────────────────────────

    def _build_tax_totals_data(self):
        """Compute the tax totals summary for a single order.

        Shared helper called by both ``_compute_amounts`` (stored monetary
        fields) and ``_compute_tax_totals`` (non-stored display field).

        :return: dict with ``base_amount_currency``, ``tax_amount_currency``,
                 ``total_amount_currency``, and detailed tax breakdown
        :rtype: dict
        """
        self.ensure_one()
        AccountTax = self.env["account.tax"]
        order_lines = self.line_ids.filtered(lambda line: not line.display_type)
        base_lines = [
            line._prepare_base_line_for_taxes_computation() for line in order_lines
        ]
        base_lines += self._get_additional_base_lines()
        AccountTax._add_tax_details_in_base_lines(base_lines, self.company_id)
        AccountTax._round_base_lines_tax_details(base_lines, self.company_id)
        return AccountTax._get_tax_totals_summary(
            base_lines=base_lines,
            currency=self.currency_id or self.company_id.currency_id,
            company=self.company_id,
        )

    def _get_additional_base_lines(self):
        """Hook for additional base lines in tax computation.

        Sale overrides to add early payment discount lines.

        :return: list of base line dicts for tax computation
        :rtype: list
        """
        return []

    @api.depends_context("lang")
    @api.depends(
        "company_id",
        "currency_id",
        "payment_term_id",
        "line_ids.price_subtotal",
    )
    def _compute_tax_totals(self):
        """Compute the ``tax_totals`` summary — the single source of truth.

        This is the only place the ``account.tax`` engine is invoked for the
        order; both the display field and the stored monetary totals
        (``_compute_amounts``) derive from this one computation.
        """
        for order in self:
            order.tax_totals = order._build_tax_totals_data()

    @api.depends("tax_totals")
    def _compute_amounts(self):
        """Derive the stored monetary totals from the ``tax_totals`` summary.

        ``tax_totals`` is the source of truth (see ``_compute_tax_totals``);
        projecting the three scalars out of it runs the tax engine **once** per
        order per recompute instead of twice (upstream recomputes it here too).
        Within a request ``tax_totals`` is computed once and cached, so the
        display widget reuses it for free.
        """
        for order in self:
            tax_totals = order.tax_totals
            order.amount_untaxed = tax_totals["base_amount_currency"]
            order.amount_tax = tax_totals["tax_amount_currency"]
            order.amount_total = tax_totals["total_amount_currency"]

    # ─── Invoice Amounts ───────────────────────────────────────────

    @api.depends(
        "line_ids.amount_taxexc_invoiced",
        "line_ids.amount_taxexc_to_invoice",
        "line_ids.amount_taxinc_invoiced",
        "line_ids.amount_taxinc_to_invoice",
    )
    def _compute_amounts_invoice(self):
        """Compute order-level invoice amounts as the sum of line amounts.

        Single-pass iteration — identical in sale.order and purchase.order.
        """
        for order in self:
            taxexc_invoiced = 0.0
            taxexc_to_invoice = 0.0
            taxinc_invoiced = 0.0
            taxinc_to_invoice = 0.0

            for line in order.line_ids:
                taxexc_invoiced += line.amount_taxexc_invoiced
                taxexc_to_invoice += line.amount_taxexc_to_invoice
                taxinc_invoiced += line.amount_taxinc_invoiced
                taxinc_to_invoice += line.amount_taxinc_to_invoice

            order.amount_taxexc_invoiced = taxexc_invoiced
            order.amount_taxexc_to_invoice = taxexc_to_invoice
            order.amount_taxinc_invoiced = taxinc_invoiced
            order.amount_taxinc_to_invoice = taxinc_to_invoice

    # ─── Credit Warning ────────────────────────────────────────────

    @api.depends("company_id", "partner_id", "amount_total")
    def _compute_partner_credit_warning(self):
        """Warn about the partner credit limit on draft orders."""
        for order in self:
            order = order.with_company(order.company_id)
            order.partner_credit_warning = ""
            show_warning = (
                order.state == "draft" and order.company_id.account_use_credit_limit
            )
            if show_warning:
                order.partner_credit_warning = self.env[
                    "account.move"
                ]._build_credit_warning_message(
                    order.sudo(),  # ensure access to `credit` & `credit_limit` fields
                    current_amount=(order.amount_total / (order.currency_rate or 1.0)),
                )

