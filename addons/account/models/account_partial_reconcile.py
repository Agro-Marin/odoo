import json
from datetime import timedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import frozendict


def _get_matching_number2lines(partials):
    """Group reconciled line IDs by their component's oldest partial ID."""
    parent = {}
    component_size = {}
    component_number = {}

    def find(line_id):
        root_id = line_id
        while parent[root_id] != root_id:
            root_id = parent[root_id]
        while parent[line_id] != line_id:
            next_id = parent[line_id]
            parent[line_id] = root_id
            line_id = next_id
        return root_id

    for partial in partials:
        debit_id = partial.debit_move_id.id
        credit_id = partial.credit_move_id.id
        for line_id in (debit_id, credit_id):
            if line_id not in parent:
                parent[line_id] = line_id
                component_size[line_id] = 1
                component_number[line_id] = partial.id

        debit_root = find(debit_id)
        credit_root = find(credit_id)
        if debit_root == credit_root:
            component_number[debit_root] = min(component_number[debit_root], partial.id)
            continue

        if component_size[debit_root] < component_size[credit_root]:
            debit_root, credit_root = credit_root, debit_root
        parent[credit_root] = debit_root
        component_size[debit_root] += component_size.pop(credit_root)
        component_number[debit_root] = min(
            component_number[debit_root],
            component_number.pop(credit_root),
            partial.id,
        )

    number2lines = {}
    for line_id in parent:
        root_id = find(line_id)
        number2lines.setdefault(component_number[root_id], []).append(line_id)
    return number2lines


def _get_partial_company(partial):
    if partial.debit_move_id.move_id.is_invoice(include_receipts=True):
        return partial.debit_move_id.company_id
    return partial.credit_move_id.company_id


class AccountPartialReconcile(models.Model):
    _name = "account.partial.reconcile"
    _description = "Partial Reconcile"

    debit_move_id = fields.Many2one(
        comodel_name="account.move.line", index=True, required=True
    )
    credit_move_id = fields.Many2one(
        comodel_name="account.move.line", index=True, required=True
    )
    full_reconcile_id = fields.Many2one(
        comodel_name="account.full.reconcile",
        string="Full Reconcile",
        copy=False,
        index="btree_not_null",
    )
    exchange_move_id = fields.Many2one(
        comodel_name="account.move", index="btree_not_null"
    )

    draft_caba_move_vals = fields.Json(
        string="Values that created the draft cash-basis entry"
    )

    company_currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Company Currency",
        related="company_id.currency_id",
        help="Utility field to express amount currency",
    )
    debit_currency_id = fields.Many2one(
        comodel_name="res.currency",
        store=True,
        related="debit_move_id.currency_id",
        precompute=True,
        string="Currency of the debit journal item.",
    )
    credit_currency_id = fields.Many2one(
        comodel_name="res.currency",
        store=True,
        related="credit_move_id.currency_id",
        precompute=True,
        string="Currency of the credit journal item.",
    )

    amount = fields.Monetary(
        currency_field="company_currency_id",
        required=True,
        help="Non-negative amount concerned by this matching expressed in the company currency.",
    )
    debit_amount_currency = fields.Monetary(
        currency_field="debit_currency_id",
        required=True,
        help="Non-negative amount concerned by this matching expressed in the debit line foreign currency.",
    )
    credit_amount_currency = fields.Monetary(
        currency_field="credit_currency_id",
        required=True,
        help="Non-negative amount concerned by this matching expressed in the credit line foreign currency.",
    )

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        store=True,
        readonly=False,
        precompute=True,
        compute="_compute_company_id",
    )
    max_date = fields.Date(
        string="Max Date of Matched Lines",
        store=True,
        precompute=True,
        compute="_compute_max_date",
    )

    _check_distinct_move_lines = models.Constraint(
        "CHECK(debit_move_id != credit_move_id)",
        "A journal item cannot be reconciled with itself.",
    )
    _check_nonnegative_amounts = models.Constraint(
        "CHECK(amount >= 0 AND debit_amount_currency >= 0 AND credit_amount_currency >= 0)",
        "Partial reconciliation amounts cannot be negative.",
    )

    @api.constrains("debit_currency_id", "credit_currency_id")
    def _check_required_computed_currencies(self):
        bad_partials = self.filtered(
            lambda partial: (
                not partial.debit_currency_id or not partial.credit_currency_id
            )
        )
        if bad_partials:
            raise ValidationError(
                _(
                    "Missing foreign currencies on partials having ids: %s",
                    bad_partials.ids,
                )
            )

    @api.constrains("debit_move_id", "credit_move_id", "company_id")
    def _check_company_consistency(self):
        bad_partials = self.filtered(
            lambda partial: (
                partial.debit_move_id.company_id.root_id
                != partial.credit_move_id.company_id.root_id
                or partial.company_id != _get_partial_company(partial)
            )
        )
        if bad_partials:
            raise ValidationError(
                _(
                    "Partial reconciliations must belong to the same company hierarchy and use the invoice-side company."
                )
            )

    @api.constrains("debit_move_id", "credit_move_id")
    def _check_move_line_directions(self):
        bad_partials = self.filtered(
            lambda partial: (
                not (
                    partial.debit_move_id.balance > 0.0
                    or partial.debit_move_id.amount_currency > 0.0
                )
                or not (
                    partial.credit_move_id.balance < 0.0
                    or partial.credit_move_id.amount_currency < 0.0
                )
            )
        )
        if bad_partials:
            raise ValidationError(
                _(
                    "The debit journal item must have a positive residual direction and the credit journal item a negative one."
                )
            )

    @api.depends("debit_move_id.date", "credit_move_id.date")
    def _compute_max_date(self):
        for partial in self:
            partial.max_date = max(
                filter(
                    None,
                    [partial.debit_move_id.date, partial.credit_move_id.date],
                ),
                default=False,
            )

    @api.depends("debit_move_id", "credit_move_id")
    def _compute_company_id(self):
        for partial in self:
            partial.company_id = _get_partial_company(partial)

    def unlink(self):
        if not self:
            return True

        to_update_payments = self._get_to_update_payments(from_state="paid")
        moves_to_reverse = self.env["account.move"].search(
            [("tax_cash_basis_rec_id", "in", self.ids)]
        )
        moves_to_reverse += self.exchange_move_id

        full_to_unlink = self.full_reconcile_id

        all_reconciled = self.debit_move_id + self.credit_move_id

        res = super().unlink()

        full_to_unlink.unlink()

        if moves_to_reverse:
            not_draft_moves = moves_to_reverse.filtered(lambda m: m.state != "draft")
            draft_moves = moves_to_reverse - not_draft_moves
            default_values_list = [
                {
                    "date": move._get_accounting_date(
                        move.date, move._affect_tax_report()
                    ),
                    "ref": move.env._("Reversal of: %s", move.name),
                }
                for move in not_draft_moves
            ]
            not_draft_moves._reverse_moves(default_values_list, cancel=True)
            draft_moves.unlink()

        all_reconciled = all_reconciled.exists()
        self._update_matching_number(all_reconciled)
        to_update_payments.state = "in_process"
        return res

    @api.model_create_multi
    def create(self, vals_list):
        partials = super().create(vals_list)
        partials._get_to_update_payments(from_state="in_process").state = "paid"
        self._update_matching_number(partials.debit_move_id + partials.credit_move_id)
        return partials

    def _get_to_update_payments(self, from_state):
        to_update_ids = set()
        group_amounts = {}
        counted_invoice_ids = set()
        for partial in self:
            matched_payments = (
                partial.credit_move_id | partial.debit_move_id
            ).move_id.matched_payment_ids
            to_check_payments = matched_payments.filtered(
                lambda payment: (
                    not payment.outstanding_account_id and payment.state == from_state
                )
            )
            for payment in to_check_payments:
                if payment.payment_type == "inbound":
                    amount = partial.debit_amount_currency
                else:
                    amount = -partial.credit_amount_currency
                if not payment.currency_id.compare_amounts(
                    payment.amount_signed, amount
                ):
                    to_update_ids.add(payment.id)
                    break

                if len(payment.invoice_ids) <= 1:
                    continue
                for invoice in payment.invoice_ids:
                    invoice_key = (payment.id, invoice.id)
                    if invoice_key in counted_invoice_ids:
                        continue
                    if payment.currency_id.compare_amounts(
                        invoice.amount_total_signed, amount
                    ):
                        continue
                    counted_invoice_ids.add(invoice_key)
                    group_amounts[payment.id] = (
                        group_amounts.get(payment.id, 0.0) + amount
                    )
                    break

        for payment in self.env["account.payment"].browse(group_amounts):
            if not payment.currency_id.compare_amounts(
                payment.amount_signed, group_amounts[payment.id]
            ):
                to_update_ids.add(payment.id)
        return self.env["account.payment"].browse(to_update_ids)

    @api.model
    def _update_matching_number(self, amls):
        amls = amls._all_reconciled_lines()
        all_partials = amls.matched_debit_ids | amls.matched_credit_ids
        number2lines = _get_matching_number2lines(all_partials)

        amls.flush_recordset(["full_reconcile_id"])
        self.env.cr.execute_values(
            """
            UPDATE account_move_line l
               SET matching_number = CASE
                       WHEN l.full_reconcile_id IS NOT NULL THEN l.full_reconcile_id::text
                       ELSE 'P' || source.number
                   END
              FROM (VALUES %s) AS source(number, ids)
             WHERE l.id = ANY(source.ids)
        """,
            list(number2lines.items()),
            page_size=1000,
        )
        processed_amls = self.env["account.move.line"].browse(
            [_id for ids in number2lines.values() for _id in ids]
        )
        processed_amls.invalidate_recordset(["matching_number"])
        (amls - processed_amls).matching_number = False

    def _collect_tax_cash_basis_values(self):
        tax_cash_basis_values_per_move = {}
        collected_per_move = {}

        if not self:
            return {}

        for partial in self:
            for field, counterpart_field in (("debit", "credit"), ("credit", "debit")):
                move, counterpart_move = (
                    partial[f"{field}_move_id"].move_id,
                    partial[f"{counterpart_field}_move_id"].move_id,
                )
                if move == counterpart_move:
                    continue

                if move.id not in collected_per_move:
                    collected_per_move[move.id] = move._collect_tax_cash_basis_values()
                move_values = collected_per_move[move.id]

                if not move_values:
                    continue

                journal = partial.company_id.tax_cash_basis_journal_id

                if not journal:
                    raise UserError(
                        _(
                            "There is no tax cash basis journal defined for the '%s' company.\n"
                            "Configure it in Accounting/Configuration/Settings",
                            partial.company_id.display_name,
                        )
                    )

                partial_amount = 0.0
                partial_amount_currency = 0.0
                rate_amount = 0.0
                rate_amount_currency = 0.0

                if partial.debit_move_id.move_id == move:
                    partial_amount += partial.amount
                    partial_amount_currency += partial.debit_amount_currency
                    rate_amount -= partial.credit_move_id.balance
                    rate_amount_currency -= partial.credit_move_id.amount_currency
                    source_line = partial.debit_move_id
                    counterpart_line = partial.credit_move_id

                if partial.credit_move_id.move_id == move:
                    partial_amount += partial.amount
                    partial_amount_currency += partial.credit_amount_currency
                    rate_amount += partial.debit_move_id.balance
                    rate_amount_currency += partial.debit_move_id.amount_currency
                    source_line = partial.credit_move_id
                    counterpart_line = partial.debit_move_id

                if all(
                    candidate.is_invoice(include_receipts=True)
                    for candidate in move | counterpart_move
                ):
                    rate_amount = source_line.balance
                    rate_amount_currency = source_line.amount_currency
                    payment_date = move.date
                else:
                    payment_date = counterpart_line.date

                if move_values["currency"] == move.company_id.currency_id:
                    if move.company_currency_id.is_zero(partial_amount):
                        continue

                    percentage = partial_amount / move_values["total_balance"]
                else:
                    if move.currency_id.is_zero(partial_amount_currency):
                        continue

                    percentage = (
                        partial_amount_currency / move_values["total_amount_currency"]
                    )

                if source_line.currency_id != counterpart_line.currency_id:
                    if "forced_rate_from_register_payment" in self.env.context:
                        payment_rate = self.env.context[
                            "forced_rate_from_register_payment"
                        ]
                    else:
                        payment_rate = self.env["res.currency"]._get_conversion_rate(
                            counterpart_line.company_currency_id,
                            source_line.currency_id,
                            counterpart_line.company_id,
                            payment_date,
                        )
                elif rate_amount:
                    payment_rate = rate_amount_currency / rate_amount
                else:
                    payment_rate = 0.0

                tax_cash_basis_values_per_move[move.id] = move_values

                partial_vals = {
                    "partial": partial,
                    "percentage": percentage,
                    "payment_rate": payment_rate,
                    "both_move_posted": partial.debit_move_id.move_id.state == "posted"
                    and partial.credit_move_id.move_id.state == "posted",
                    "payment_date": payment_date,
                    "counterpart_move": counterpart_move,
                }

                move_values.setdefault("partials", [])
                move_values["partials"].append(partial_vals)

        return tax_cash_basis_values_per_move

    @api.model
    def _prepare_cash_basis_base_line_vals(self, base_line, balance, amount_currency):
        account = (
            base_line.company_id.account_cash_basis_base_account_id
            or base_line.account_id
        )
        tax_ids = base_line.tax_ids.flatten_taxes_hierarchy().filtered(
            lambda x: x.tax_exigibility == "on_payment"
        )
        is_refund = base_line.is_refund
        tax_tags = tax_ids._get_repartition_tags(is_refund, "base")
        product_tags = base_line.tax_tag_ids.filtered(
            lambda x: x.applicability == "products"
        )
        all_tags = tax_tags + product_tags

        return {
            "name": base_line.move_id.name,
            "debit": max(0.0, balance),
            "credit": -balance if balance < 0.0 else 0.0,
            "amount_currency": amount_currency,
            "currency_id": base_line.currency_id.id,
            "partner_id": base_line.partner_id.id,
            "account_id": account.id,
            "tax_ids": [Command.set(tax_ids.ids)],
            "tax_tag_ids": [Command.set(all_tags.ids)],
            "analytic_distribution": base_line.analytic_distribution,
            "display_type": base_line.display_type,
        }

    @api.model
    def _prepare_cash_basis_counterpart_base_line_vals(self, cb_base_line_vals):
        return {
            "name": cb_base_line_vals["name"],
            "debit": cb_base_line_vals["credit"],
            "credit": cb_base_line_vals["debit"],
            "account_id": cb_base_line_vals["account_id"],
            "amount_currency": -cb_base_line_vals["amount_currency"],
            "currency_id": cb_base_line_vals["currency_id"],
            "partner_id": cb_base_line_vals["partner_id"],
            "analytic_distribution": cb_base_line_vals["analytic_distribution"],
            "display_type": cb_base_line_vals["display_type"],
        }

    @api.model
    def _prepare_cash_basis_tax_line_vals(self, tax_line, balance, amount_currency):
        tax_ids = tax_line.tax_ids.filtered(lambda x: x.tax_exigibility == "on_payment")
        base_tags = tax_ids._get_repartition_tags(
            tax_line.tax_repartition_line_id.filtered(
                lambda rl: rl.document_type == "refund"
            ).tax_id,
            "base",
        )
        product_tags = tax_line.tax_tag_ids.filtered(
            lambda x: x.applicability == "products"
        )
        all_tags = base_tags + tax_line.tax_repartition_line_id.tag_ids + product_tags

        return {
            "name": tax_line.name,
            "debit": max(0.0, balance),
            "credit": -balance if balance < 0.0 else 0.0,
            "tax_base_amount": tax_line.tax_base_amount,
            "tax_repartition_line_id": tax_line.tax_repartition_line_id.id,
            "tax_ids": [Command.set(tax_ids.ids)],
            "tax_tag_ids": [Command.set(all_tags.ids)],
            "account_id": tax_line.tax_repartition_line_id.account_id.id
            or tax_line.company_id.account_cash_basis_base_account_id.id
            or tax_line.account_id.id,
            "amount_currency": amount_currency,
            "currency_id": tax_line.currency_id.id,
            "partner_id": tax_line.partner_id.id,
            "analytic_distribution": tax_line.analytic_distribution,
            "display_type": tax_line.display_type,
        }

    @api.model
    def _prepare_cash_basis_counterpart_tax_line_vals(self, tax_line, cb_tax_line_vals):
        return {
            "name": cb_tax_line_vals["name"],
            "debit": cb_tax_line_vals["credit"],
            "credit": cb_tax_line_vals["debit"],
            "account_id": tax_line.account_id.id,
            "amount_currency": -cb_tax_line_vals["amount_currency"],
            "currency_id": cb_tax_line_vals["currency_id"],
            "partner_id": cb_tax_line_vals["partner_id"],
            "analytic_distribution": cb_tax_line_vals["analytic_distribution"],
            "display_type": cb_tax_line_vals["display_type"],
        }

    @api.model
    def _get_cash_basis_base_line_grouping_key_from_vals(self, base_line_vals):
        tax_ids = base_line_vals["tax_ids"][0][2]
        base_taxes = self.env["account.tax"].browse(tax_ids)
        return (
            base_line_vals["currency_id"],
            base_line_vals["partner_id"],
            base_line_vals["account_id"],
            tuple(base_taxes.filtered(lambda x: x.tax_exigibility == "on_payment").ids),
            tuple(sorted(base_line_vals["tax_tag_ids"][0][2])),
            frozendict(base_line_vals["analytic_distribution"] or {}),
        )

    @api.model
    def _get_cash_basis_base_line_grouping_key_from_record(
        self, base_line, account=None
    ):
        return (
            base_line.currency_id.id,
            base_line.partner_id.id,
            (account or base_line.account_id).id,
            tuple(
                base_line.tax_ids.flatten_taxes_hierarchy()
                .filtered(lambda x: x.tax_exigibility == "on_payment")
                .ids
            ),
            tuple(sorted(base_line.tax_tag_ids.ids)),
            frozendict(base_line.analytic_distribution or {}),
        )

    @api.model
    def _get_cash_basis_tax_line_grouping_key_from_vals(self, tax_line_vals):
        tax_ids = tax_line_vals["tax_ids"][0][2]
        base_taxes = self.env["account.tax"].browse(tax_ids)
        return (
            tax_line_vals["currency_id"],
            tax_line_vals["partner_id"],
            tax_line_vals["account_id"],
            tuple(base_taxes.filtered(lambda x: x.tax_exigibility == "on_payment").ids),
            tax_line_vals["tax_repartition_line_id"],
            tuple(sorted(tax_line_vals["tax_tag_ids"][0][2])),
            frozendict(tax_line_vals["analytic_distribution"] or {}),
        )

    @api.model
    def _get_cash_basis_tax_line_grouping_key_from_record(self, tax_line, account=None):
        return (
            tax_line.currency_id.id,
            tax_line.partner_id.id,
            (account or tax_line.account_id).id,
            tuple(
                tax_line.tax_ids.filtered(
                    lambda x: x.tax_exigibility == "on_payment"
                ).ids
            ),
            tax_line.tax_repartition_line_id.id,
            tuple(sorted(tax_line.tax_tag_ids.ids)),
            frozendict(tax_line.analytic_distribution or {}),
        )

    def _create_tax_cash_basis_moves(self):
        tax_cash_basis_values_per_move = self._collect_tax_cash_basis_values()
        moves_to_create = []
        post_after_create = []
        to_reconcile_after = []
        for move_values in tax_cash_basis_values_per_move.values():
            move = move_values["move"]
            amount_residual_per_tax_line = {
                line.id: line.amount_residual_currency
                for line_type, line in move_values["to_process_lines"]
                if line_type == "tax"
            }

            for partial_values in move_values["partials"]:
                partial = partial_values["partial"]

                journal = partial.company_id.tax_cash_basis_journal_id
                lock_date = move.company_id._get_user_fiscal_lock_date(journal)
                move_date = max(
                    partial_values["payment_date"], lock_date + timedelta(days=1)
                )
                move_vals = {
                    "move_type": "entry",
                    "date": move_date,
                    "ref": move.name,
                    "journal_id": journal.id,
                    "company_id": partial.company_id.id,
                    "line_ids": [],
                    "tax_cash_basis_rec_id": partial.id,
                    "tax_cash_basis_origin_move_id": move.id,
                    "fiscal_position_id": move.fiscal_position_id.id,
                }

                partial_lines_to_create = {}

                for caba_treatment, line in move_values["to_process_lines"]:
                    amount_currency = line.currency_id.round(
                        line.amount_currency * partial_values["percentage"]
                    )
                    if (
                        caba_treatment == "tax"
                        and (
                            move_values["is_fully_paid"]
                            or line.currency_id.compare_amounts(
                                abs(line.amount_residual_currency), abs(amount_currency)
                            )
                            < 0
                        )
                        and partial_values == move_values["partials"][-1]
                    ):
                        amount_currency = amount_residual_per_tax_line[line.id]
                    if caba_treatment == "tax":
                        amount_residual_per_tax_line[line.id] -= amount_currency
                    balance = (
                        partial_values["payment_rate"]
                        and amount_currency / partial_values["payment_rate"]
                    ) or 0.0

                    if caba_treatment == "tax":
                        cb_line_vals = self._prepare_cash_basis_tax_line_vals(
                            line, balance, amount_currency
                        )
                        grouping_key = (
                            self._get_cash_basis_tax_line_grouping_key_from_vals(
                                cb_line_vals
                            )
                        )
                    elif caba_treatment == "base":
                        cb_line_vals = self._prepare_cash_basis_base_line_vals(
                            line, balance, amount_currency
                        )
                        cb_line_vals["name"] = " - ".join(
                            filter(
                                None,
                                (
                                    line.move_id.name,
                                    partial_values["counterpart_move"].name,
                                ),
                            )
                        )

                        grouping_key = (
                            self._get_cash_basis_base_line_grouping_key_from_vals(
                                cb_line_vals
                            )
                        )

                    if grouping_key in partial_lines_to_create:
                        aggregated_vals = partial_lines_to_create[grouping_key]["vals"]

                        debit = aggregated_vals["debit"] + cb_line_vals["debit"]
                        credit = aggregated_vals["credit"] + cb_line_vals["credit"]
                        balance = debit - credit

                        aggregated_vals.update(
                            {
                                "debit": max(0, balance),
                                "credit": -balance if balance < 0 else 0,
                                "amount_currency": aggregated_vals["amount_currency"]
                                + cb_line_vals["amount_currency"],
                            }
                        )

                        if caba_treatment == "tax":
                            aggregated_vals.update(
                                {
                                    "tax_base_amount": aggregated_vals[
                                        "tax_base_amount"
                                    ]
                                    + cb_line_vals["tax_base_amount"],
                                }
                            )
                            partial_lines_to_create[grouping_key]["tax_line"] += line
                    else:
                        partial_lines_to_create[grouping_key] = {
                            "vals": cb_line_vals,
                        }
                        if caba_treatment == "tax":
                            partial_lines_to_create[grouping_key].update(
                                {
                                    "tax_line": line,
                                }
                            )

                sequence = 0

                for aggregated_vals in partial_lines_to_create.values():
                    line_vals = aggregated_vals["vals"]
                    line_vals["sequence"] = sequence

                    if "tax_repartition_line_id" in line_vals:
                        tax_line = aggregated_vals["tax_line"]
                        counterpart_line_vals = (
                            self._prepare_cash_basis_counterpart_tax_line_vals(
                                tax_line, line_vals
                            )
                        )
                        counterpart_line_vals["sequence"] = sequence + 1

                        if tax_line.account_id.reconcile:
                            move_index = len(moves_to_create)
                            to_reconcile_after.append(
                                (
                                    tax_line,
                                    move_index,
                                    counterpart_line_vals["sequence"],
                                )
                            )
                    else:
                        counterpart_line_vals = (
                            self._prepare_cash_basis_counterpart_base_line_vals(
                                line_vals
                            )
                        )
                        counterpart_line_vals["sequence"] = sequence + 1

                    sequence += 2

                    move_vals["line_ids"] += [
                        (0, 0, counterpart_line_vals),
                        (0, 0, line_vals),
                    ]

                moves_to_create.append(move_vals)
                post_after_create.append(partial_values["both_move_posted"])

        moves = (
            self.env["account.move"]
            .with_context(
                skip_invoice_sync=True,
                skip_invoice_line_sync=True,
                skip_account_move_synchronization=True,
            )
            .create(moves_to_create)
        )
        moves.browse(
            move.id for move, post in zip(moves, post_after_create, strict=True) if post
        )._post(soft=False)

        reconciliation_plan = []
        for lines, move_index, sequence in to_reconcile_after:
            lines = lines.filtered(lambda x: not x.reconciled)
            if not lines:
                continue

            counterpart_line = moves[move_index].line_ids.filtered(
                lambda line, sequence=sequence: line.sequence == sequence
            )

            if counterpart_line.reconciled:
                continue

            reconciliation_plan.append(counterpart_line + lines)

        self.env["account.move.line"].with_context(add_caba_vals=True)._reconcile_plan(
            reconciliation_plan
        )
        return moves

    def _get_draft_caba_move_vals(self):
        self.ensure_one()
        debit_vals = self.debit_move_id.move_id._collect_tax_cash_basis_values() or {}
        credit_vals = self.credit_move_id.move_id._collect_tax_cash_basis_values() or {}
        if not debit_vals and not credit_vals:
            return False
        return json.dumps(
            {
                "debit_caba_lines": [
                    (aml_type, aml.id)
                    for aml_type, aml in debit_vals.get("to_process_lines", [])
                ],
                "debit_total_balance": debit_vals.get("total_balance"),
                "debit_total_amount_currency": debit_vals.get("total_amount_currency"),
                "credit_caba_lines": [
                    (aml_type, aml.id)
                    for aml_type, aml in credit_vals.get("to_process_lines", [])
                ],
                "credit_total_balance": credit_vals.get("total_balance"),
                "credit_total_amount_currency": credit_vals.get(
                    "total_amount_currency"
                ),
            }
        )

    def _set_draft_caba_move_vals(self):
        for partial in self:
            partial.draft_caba_move_vals = partial._get_draft_caba_move_vals()
