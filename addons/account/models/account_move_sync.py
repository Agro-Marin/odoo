from collections import Counter, defaultdict
from contextlib import ExitStack, contextmanager

from odoo import _, api, models
from odoo.fields import Command
from odoo.tools import float_compare, frozendict
from odoo.tools.misc import clean_context

from odoo.addons.account.tools.dynamic_lines import plan_dynamic_line_sync


class AccountMove(models.Model):
    _inherit = "account.move"

    def _recompute_cash_rounding_lines(self):
        self.ensure_one()


        def _compute_cash_rounding(self, total_amount_currency):
            difference = self.invoice_cash_rounding_id.compute_difference(
                self.currency_id, total_amount_currency
            )
            if self.currency_id == self.company_id.currency_id:
                diff_amount_currency = diff_balance = difference
            else:
                diff_amount_currency = difference
                diff_balance = self.currency_id._convert(
                    diff_amount_currency,
                    self.company_id.currency_id,
                    self.company_id,
                    self.invoice_date or self.date,
                )
            return diff_balance, diff_amount_currency

        def _apply_cash_rounding(
            self, diff_balance, diff_amount_currency, cash_rounding_line
        ):
            rounding_line_vals = {
                "balance": diff_balance,
                "amount_currency": diff_amount_currency,
                "partner_id": self.commercial_partner_id.id,
                "move_id": self.id,
                "currency_id": self.currency_id.id,
                "company_id": self.company_id.id,
                "company_currency_id": self.company_id.currency_id.id,
                "display_type": "rounding",
            }

            if self.invoice_cash_rounding_id.strategy == "biggest_tax":
                biggest_tax_line = None
                for tax_line in self.line_ids.filtered("tax_repartition_line_id"):
                    if not biggest_tax_line or abs(tax_line.balance) > abs(
                        biggest_tax_line.balance
                    ):
                        biggest_tax_line = tax_line

                if not biggest_tax_line:
                    return

                rounding_line_vals.update(
                    {
                        "name": _(
                            "%(tax_name)s (rounding)", tax_name=biggest_tax_line.name
                        ),
                        "account_id": biggest_tax_line.account_id.id,
                        "tax_repartition_line_id": biggest_tax_line.tax_repartition_line_id.id,
                        "tax_tag_ids": [Command.set(biggest_tax_line.tax_tag_ids.ids)],
                        "tax_ids": [Command.set(biggest_tax_line.tax_ids.ids)],
                    }
                )
            elif self.invoice_cash_rounding_id.strategy == "add_invoice_line":
                if diff_balance > 0.0 and self.invoice_cash_rounding_id.loss_account_id:
                    account_id = self.invoice_cash_rounding_id.loss_account_id.id
                else:
                    account_id = self.invoice_cash_rounding_id.profit_account_id.id
                rounding_line_vals.update(
                    {
                        "name": self.invoice_cash_rounding_id.name,
                        "account_id": account_id,
                        "tax_ids": [Command.clear()],
                    }
                )

            if cash_rounding_line:
                cash_rounding_line.write(rounding_line_vals)
            else:
                cash_rounding_line = self.env["account.move.line"].create(
                    rounding_line_vals
                )

        existing_cash_rounding_line = self.line_ids.filtered(
            lambda line: line.display_type == "rounding"
        )

        if not self.invoice_cash_rounding_id:
            existing_cash_rounding_line.unlink()
            return

        if self.invoice_cash_rounding_id and existing_cash_rounding_line:
            strategy = self.invoice_cash_rounding_id.strategy
            old_strategy = (
                "biggest_tax"
                if existing_cash_rounding_line.tax_line_id
                else "add_invoice_line"
            )
            if strategy != old_strategy:
                existing_cash_rounding_line.unlink()
                existing_cash_rounding_line = self.env["account.move.line"]

        others_lines = self.line_ids.filtered(
            lambda line: (
                line.account_id.account_type
                not in ("asset_receivable", "liability_payable")
            )
        )
        others_lines -= existing_cash_rounding_line
        total_amount_currency = sum(others_lines.mapped("amount_currency"))

        diff_balance, diff_amount_currency = _compute_cash_rounding(
            self, total_amount_currency
        )

        if self.company_currency_id.is_zero(diff_balance) and self.currency_id.is_zero(
            diff_amount_currency
        ):
            existing_cash_rounding_line.unlink()
            return

        if (
            existing_cash_rounding_line
            and float_compare(
                existing_cash_rounding_line.balance,
                diff_balance,
                precision_rounding=self.company_currency_id.rounding,
            )
            == 0
            and float_compare(
                existing_cash_rounding_line.amount_currency,
                diff_amount_currency,
                precision_rounding=self.currency_id.rounding,
            )
            == 0
        ):
            return

        _apply_cash_rounding(
            self, diff_balance, diff_amount_currency, existing_cash_rounding_line
        )

    def _get_automatic_balancing_account(self):
        self.ensure_one()
        if self.journal_id.default_account_id:
            return self.journal_id.default_account_id.id
        return self.company_id.account_journal_suspense_account_id.id

    @contextmanager
    def _sync_unbalanced_lines(self, container):
        def has_tax(move):
            return bool(move.line_ids.tax_ids)

        move_had_tax = {move: has_tax(move) for move in container["records"]}
        yield  # noqa: RUF075 - deliberate: on exception the transaction aborts/rolls back, so skipping this sync's post-yield step changes nothing that would otherwise persist
        balance_name = _("Automatic Balancing Line")
        balancing_line_by_move = {}
        for move in (x for x in container["records"] if x.state == "draft"):
            if not has_tax(move) and not move_had_tax.get(move):
                continue
            if move_had_tax.get(move) and not has_tax(move):
                move.line_ids.filtered("tax_line_id").unlink()
                move.line_ids.tax_tag_ids = [Command.set([])]

            existing_balancing_line = move.line_ids.filtered(
                lambda line: (
                    line.display_type == "balancing" or line.name == balance_name
                )
            )
            if existing_balancing_line:
                existing_balancing_line.balance = (
                    existing_balancing_line.amount_currency
                ) = 0.0
            balancing_line_by_move[move] = existing_balancing_line

        if not balancing_line_by_move:
            return

        unbalanced_by_move_id = {
            move_id: (debit, credit)
            for move_id, debit, credit in (
                self._get_unbalanced_moves(
                    {"records": self.env["account.move"].union(*balancing_line_by_move)}
                )
                or []
            )
        }

        for move, existing_balancing_line in balancing_line_by_move.items():
            unbalanced = unbalanced_by_move_id.get(move.id)
            if unbalanced:
                debit, credit = unbalanced
                balance = credit - debit
                if existing_balancing_line:
                    existing_balancing_line.write(
                        {
                            "balance": balance,
                            "amount_currency": existing_balancing_line.currency_id.round(
                                balance * existing_balancing_line.currency_rate
                            ),
                        }
                    )
                else:
                    self.env["account.move.line"].create(
                        {
                            "balance": balance,
                            "name": balance_name,
                            "display_type": "balancing",
                            "move_id": move.id,
                            "account_id": move._get_automatic_balancing_account(),
                            "currency_id": move.currency_id.id,
                            "tax_ids": False,
                        }
                    )
            elif existing_balancing_line:
                existing_balancing_line.unlink()

    @contextmanager
    def _sync_rounding_lines(self, container):
        yield  # noqa: RUF075 - deliberate: on exception the transaction aborts/rolls back, so skipping this sync's post-yield step changes nothing that would otherwise persist
        for invoice in container["records"]:
            if invoice.state == "draft":
                invoice._recompute_cash_rounding_lines()

    @api.model
    def _sync_dynamic_line_needed_values(self, values_list):
        line_fields = self.env["account.move.line"]._fields
        res = {}
        merged_keys = set()
        for computed_needed in values_list:
            if computed_needed is False:
                continue
            for key, values in computed_needed.items():
                if key not in res:
                    res[key] = dict(values)
                else:
                    merged_keys.add(key)
                    for fname in res[key]:
                        if line_fields[fname].type == "monetary":
                            res[key][fname] += values[fname]

        for key, values in res.items():
            move_id = key.get("move_id")
            if not move_id:
                continue
            record = self.env["account.move"].browse(move_id)
            for fname, current_value in values.items():
                field = line_fields[fname]
                if isinstance(current_value, float):
                    values[fname] = field.convert_to_cache(current_value, record)

        for key in merged_keys:
            values = res[key]
            if not any(
                values[fname]
                for fname in values
                if line_fields[fname].type == "monetary"
            ):
                del res[key]

        return res

    @contextmanager
    def _sync_tax_lines(self, container):
        AccountTax = self.env["account.tax"]
        fake_base_line = AccountTax._prepare_base_line_for_taxes_computation(None)

        def get_base_lines(move):
            return move.line_ids.filtered(
                lambda line: (
                    line.display_type
                    in ("product", "epd", "rounding", "cogs", "non_deductible_product")
                )
            )

        def get_tax_lines(move):
            return move.line_ids.filtered("tax_repartition_line_id")

        def get_value(record, field):
            return record._fields[field].convert_to_write(record[field], record)

        def get_tax_line_tracked_fields(line):
            return ("amount_currency", "balance", "analytic_distribution")

        def get_base_line_tracked_fields(line):
            grouping_key = AccountTax._prepare_base_line_grouping_key(fake_base_line)
            if line.move_id.is_invoice(include_receipts=True):
                extra_fields = [
                    "price_unit",
                    "quantity",
                    "discount",
                    "deductible_amount",
                ]
            else:
                extra_fields = ["amount_currency"]
            return list(grouping_key.keys()) + extra_fields

        def field_has_changed(values, record, field):
            return get_value(record, field) != values.get(record, {}).get(field)

        def get_changed_lines(values, records, fields=None):
            return (
                record
                for record in records
                if record not in values
                or any(
                    field_has_changed(values, record, field)
                    for field in values[record]
                    if not fields or field in fields
                )
            )

        def any_field_has_changed(values, records, fields=None):
            return any(record for record in get_changed_lines(values, records, fields))

        def is_write_needed(line, values):
            return any(
                self.env["account.move.line"]
                ._fields[fname]
                .convert_to_write(line[fname], self)
                != values[fname]
                for fname in values
            )

        moves_values_before = {
            move: {
                field: get_value(move, field)
                for field in (
                    "currency_id",
                    "partner_id",
                    "move_type",
                    "invoice_currency_rate",
                    "invoice_date",
                )
            }
            for move in container["records"]
        }
        base_lines_values_before = {
            move: {
                line: {
                    field: get_value(line, field)
                    for field in get_base_line_tracked_fields(line)
                }
                for line in get_base_lines(move)
            }
            for move in container["records"]
        }
        tax_lines_values_before = {
            move: {
                line: {
                    field: get_value(line, field)
                    for field in get_tax_line_tracked_fields(line)
                }
                for line in get_tax_lines(move)
            }
            for move in container["records"]
        }
        yield  # noqa: RUF075 - deliberate: on exception the transaction aborts/rolls back, so skipping this sync's post-yield step changes nothing that would otherwise persist

        to_delete = []
        to_create = []
        grouped_update = defaultdict(set)
        for move in container["records"]:
            if move.state != "draft":
                continue

            tax_lines = get_tax_lines(move)
            base_lines = get_base_lines(move)
            move_tax_lines_values_before = tax_lines_values_before.get(move, {})
            move_base_lines_values_before = base_lines_values_before.get(move, {})
            reapply_currency_rate = False
            if move.is_invoice(include_receipts=True) and (
                field_has_changed(moves_values_before, move, "currency_id")
                or field_has_changed(moves_values_before, move, "move_type")
            ):
                round_from_tax_lines = False
            elif any(
                line not in base_lines
                for line, values in move_base_lines_values_before.items()
                if values["tax_ids"]
            ):
                round_from_tax_lines = any_field_has_changed(
                    move_tax_lines_values_before, tax_lines
                )
            elif changed_lines := list(
                get_changed_lines(move_base_lines_values_before, base_lines)
            ):
                round_from_tax_lines = (
                    all(
                        not line.tax_ids
                        and not move_base_lines_values_before.get(line, {}).get(
                            "tax_ids"
                        )
                        for line in changed_lines
                    )
                    or (
                        list(move_tax_lines_values_before) != list(tax_lines)
                        or any(
                            self.env.is_protected(line._fields[fname], line)
                            for line in tax_lines
                            for fname in move_tax_lines_values_before[line]
                        )
                    )
                )

                if round_from_tax_lines and any(
                    line[field]
                    for line in changed_lines
                    for field in ("amount_currency", "balance")
                ):
                    continue
            elif field_has_changed(moves_values_before, move, "invoice_currency_rate"):
                round_from_tax_lines = True
                reapply_currency_rate = True
            else:
                continue

            base_lines_values, tax_lines_values = move._get_rounded_base_and_tax_lines(
                round_from_tax_lines=round_from_tax_lines,
                reapply_currency_rate=reapply_currency_rate,
            )
            AccountTax._add_accounting_data_in_base_lines_tax_details(
                base_lines_values,
                move.company_id,
                include_caba_tags=move.always_tax_exigible,
            )
            tax_results = AccountTax._prepare_tax_lines(
                base_lines_values, move.company_id, tax_lines=tax_lines_values
            )

            non_deductible_tax_line = move.line_ids.filtered(
                lambda line: line.display_type == "non_deductible_tax"
            )
            non_deductible_lines_values = [
                line_values
                for line_values in base_lines_values
                if line_values["special_type"] == "non_deductible"
                and line_values["tax_ids"]
            ]

            if not non_deductible_lines_values and non_deductible_tax_line:
                to_delete.append(non_deductible_tax_line.id)
            elif non_deductible_lines_values:
                non_deductible_tax_values = {
                    "tax_amount": 0.0,
                    "tax_amount_currency": 0.0,
                }
                for line_values in non_deductible_lines_values:
                    non_deductible_tax_values["tax_amount"] += -line_values["sign"] * (
                        line_values["tax_details"]["total_included"]
                        - line_values["tax_details"]["total_excluded"]
                    )
                    non_deductible_tax_values["tax_amount_currency"] += -line_values[
                        "sign"
                    ] * (
                        line_values["tax_details"]["total_included_currency"]
                        - line_values["tax_details"]["total_excluded_currency"]
                    )

                non_deductable_tax_line_values = {
                    "move_id": move.id,
                    "account_id": (
                        non_deductible_tax_line.account_id
                        or move.journal_id.non_deductible_account_id
                        or move.journal_id.default_account_id
                    ).id,
                    "display_type": "non_deductible_tax",
                    "name": _("private part (taxes)"),
                    "balance": non_deductible_tax_values["tax_amount"],
                    "amount_currency": non_deductible_tax_values["tax_amount_currency"],
                    "sequence": max(
                        move.line_ids.filtered(
                            lambda line: (
                                line.display_type
                                in (
                                    "product",
                                    "non_deductible_product",
                                    "non_deductible_product_total",
                                )
                            )
                        ).mapped("sequence"),
                        default=0,
                    )
                    + 1,
                }
                if non_deductible_tax_line:
                    tax_results["tax_lines_to_update"].append(
                        (
                            {"record": non_deductible_tax_line},
                            "unused_grouping_key",
                            {
                                "amount_currency": non_deductable_tax_line_values[
                                    "amount_currency"
                                ],
                                "balance": non_deductable_tax_line_values["balance"],
                            },
                        )
                    )
                else:
                    to_create.append(non_deductable_tax_line_values)

            for base_line, to_update in tax_results["base_lines_to_update"]:
                line = base_line["record"]
                if is_write_needed(line, to_update):
                    grouped_update[line.currency_id.id, frozendict(to_update)].add(
                        line.id
                    )

            to_delete.extend(
                tax_line_vals["record"].id
                for tax_line_vals in tax_results["tax_lines_to_delete"]
            )

            to_create.extend(
                {
                    **tax_line_vals,
                    "display_type": "tax",
                    "move_id": move.id,
                }
                for tax_line_vals in tax_results["tax_lines_to_add"]
            )

            for tax_line_vals, _grouping_key, to_update in tax_results[
                "tax_lines_to_update"
            ]:
                line = tax_line_vals["record"]
                if is_write_needed(line, to_update):
                    grouped_update[line.currency_id.id, frozendict(to_update)].add(
                        line.id
                    )

        if grouped_update:
            for (_currency_id, values), lines in grouped_update.items():
                self.env["account.move.line"].browse(lines).write(dict(values))
        if to_delete:
            self.env["account.move.line"].browse(to_delete).with_context(
                dynamic_unlink=True
            ).unlink()
        if to_create:
            self.env["account.move.line"].create(to_create)

    @contextmanager
    def _sync_non_deductible_base_lines(self, container):
        def has_non_deductible_lines(move):
            return (
                move.state == "draft"
                and move.is_purchase_document(include_receipts=True)
                and any(
                    move.line_ids.filtered(
                        lambda line: (
                            line.display_type == "product"
                            and line.deductible_amount < 100
                        )
                    )
                )
            )

        product_lines_before = {
            move: Counter(
                (
                    line.name,
                    line.price_subtotal,
                    line.tax_ids,
                    line.deductible_amount,
                    line.account_id,
                )
                for line in move.line_ids
                if line.display_type == "product"
            )
            for move in container["records"]
        }

        yield  # noqa: RUF075 - deliberate: on exception the transaction aborts/rolls back, so skipping this sync's post-yield step changes nothing that would otherwise persist

        to_delete = []
        to_create = []
        for move in container["records"]:
            product_lines_now = Counter(
                (
                    line.name,
                    line.price_subtotal,
                    line.tax_ids,
                    line.deductible_amount,
                    line.account_id,
                )
                for line in move.line_ids
                if line.display_type == "product"
            )

            has_changed_product_lines = bool(
                product_lines_before.get(move, Counter()) - product_lines_now
                or product_lines_now - product_lines_before.get(move, Counter())
            )
            if not has_changed_product_lines:
                continue

            non_deductible_base_lines = move.line_ids.filtered(
                lambda line: (
                    line.display_type
                    in ("non_deductible_product", "non_deductible_product_total")
                )
            )
            to_delete += non_deductible_base_lines.ids

            if not has_non_deductible_lines(move):
                continue

            non_deductible_amount_currency_total = 0.0
            non_deductible_balance_total = 0.0

            sign = move.direction_sign
            rate = move.invoice_currency_rate

            product_lines = move.line_ids.filtered(
                lambda line: line.display_type == "product"
            )
            total_sequence = max(product_lines.mapped("sequence")) + 1

            for line in product_lines:
                if float_compare(line.deductible_amount, 100, precision_digits=2) == 0:
                    continue

                percentage = 1 - line.deductible_amount / 100
                non_deductible_subtotal = line.currency_id.round(
                    line.price_subtotal * percentage
                )
                non_deductible_amount_currency = line.currency_id.round(
                    sign * non_deductible_subtotal
                )
                non_deductible_balance = (
                    line.company_currency_id.round(
                        sign * non_deductible_subtotal / rate
                    )
                    if rate
                    else 0.0
                )
                non_deductible_amount_currency_total += non_deductible_amount_currency
                non_deductible_balance_total += non_deductible_balance

                to_create.append(
                    {
                        "move_id": move.id,
                        "partner_id": move.commercial_partner_id.id,
                        "account_id": line.account_id.id,
                        "display_type": "non_deductible_product",
                        "name": line.name,
                        "balance": -1 * non_deductible_balance,
                        "amount_currency": -1 * non_deductible_amount_currency,
                        "tax_ids": [
                            Command.set(
                                line.tax_ids.filtered(
                                    lambda tax: tax.amount_type != "fixed"
                                ).ids
                            )
                        ],
                        "sequence": line.sequence + 1,
                    }
                )

            to_create.append(
                {
                    "move_id": move.id,
                    "partner_id": move.commercial_partner_id.id,
                    "account_id": (
                        move.journal_id.non_deductible_account_id
                        or move.journal_id.default_account_id
                    ).id,
                    "display_type": "non_deductible_product_total",
                    "name": _("private part"),
                    "balance": non_deductible_balance_total,
                    "amount_currency": non_deductible_amount_currency_total,
                    "tax_ids": [Command.clear()],
                    "sequence": total_sequence,
                }
            )

        if to_delete:
            self.env["account.move.line"].browse(to_delete).with_context(
                dynamic_unlink=True
            ).unlink()
        if to_create:
            self.env["account.move.line"].create(to_create)

    @contextmanager
    def _sync_dynamic_line(
        self,
        existing_key_fname,
        needed_vals_fname,
        needed_dirty_fname,
        line_type,
        container,
    ):
        def existing():
            if line_type == "epd":
                return {
                    line: (
                        line[existing_key_fname] or frozendict({"epd_line_id": line.id})
                    )
                    for line in container["records"].line_ids
                    if line.display_type == "epd"
                    if line[existing_key_fname] or line.id
                }
            return {
                line: line[existing_key_fname]
                for line in container["records"].line_ids
                if line[existing_key_fname]
            }

        def needed():
            return self._sync_dynamic_line_needed_values(
                container["records"].mapped(needed_vals_fname)
            )

        def dirty():
            *path, dirty_fname = needed_dirty_fname.split(".")
            eligible_recs = container["records"].mapped(".".join(path))
            if eligible_recs._name == "account.move.line":
                eligible_recs = eligible_recs.filtered(
                    lambda l: l.display_type != "cogs"
                )
            dirty_recs = eligible_recs.filtered(dirty_fname)
            return dirty_recs, dirty_fname

        inv_existing_before = existing()
        needed_before = needed()
        dirty_recs_before, dirty_fname = dirty()
        dirty_recs_before[dirty_fname] = False
        yield  # noqa: RUF075 - deliberate: on exception the transaction aborts/rolls back, so skipping this sync's post-yield step changes nothing that would otherwise persist
        dirty_recs_after, dirty_fname = dirty()
        if not dirty_recs_after:
            return
        inv_existing_after = existing()
        needed_after = needed()

        line_ids = set(
            self.env["account.move.line"]
            .browse(k["id"] for k in needed_before if "id" in k)
            .exists()
            .ids
        )
        needed_before = {
            k: v
            for k, v in needed_before.items()
            if "id" not in k or k["id"] in line_ids
        }

        def values_differ(line, values):
            line_fields = self.env["account.move.line"]._fields
            return any(
                line_fields[fname].convert_to_write(line[fname], self) != values[fname]
                for fname in values
            )

        plan = plan_dynamic_line_sync(
            inv_existing_before,
            inv_existing_after,
            needed_before,
            needed_after,
            values_differ,
        )
        if plan is None:
            return
        to_delete, to_create, to_write = plan

        if to_delete:
            self.env["account.move.line"].browse(
                [line.id for line in to_delete]
            ).exists().with_context(dynamic_unlink=True).unlink()
        if to_create:
            self.env["account.move.line"].with_context(
                clean_context(self.env.context)
            ).create(
                [
                    {**key, **values, "display_type": line_type}
                    for key, values in to_create.items()
                ]
            )
        if to_write:
            for line, values in to_write.items():
                line.write(values)

    @contextmanager
    def _sync_invoice(self, container):
        def existing():
            return {
                move: {
                    "commercial_partner_id": move.commercial_partner_id,
                }
                for move in container["records"].filtered(lambda m: m.is_invoice(True))
            }

        def changed(move, fname):
            return move not in before or before[move][fname] != after[move][fname]

        before = existing()
        yield  # noqa: RUF075 - deliberate: on exception the transaction aborts/rolls back, so skipping this sync's post-yield step changes nothing that would otherwise persist
        after = existing()

        partner_id_to_update = defaultdict(set)
        for move in after:
            if changed(move, "commercial_partner_id"):
                partner_id_to_update[after[move]["commercial_partner_id"]].update(
                    move.line_ids.ids
                )

        for partner_id, line_ids in partner_id_to_update.items():
            self.env["account.move.line"].browse(line_ids).partner_id = partner_id

    def _get_sync_stack(self, container):
        tax_container, invoice_container, misc_container = ({} for _ in range(3))

        def update_containers():
            tax_container["records"] = container["records"].filtered(
                lambda m: (
                    m.is_invoice(True)
                    or m.line_ids.tax_ids
                    or m.line_ids.tax_repartition_line_id
                )
            )
            invoice_container["records"] = container["records"].filtered(
                lambda m: m.is_invoice(True)
            )
            misc_container["records"] = container["records"].filtered(
                lambda m: m.is_entry() and not m.tax_cash_basis_origin_move_id
            )

            return tax_container, invoice_container, misc_container

        update_containers()

        stack = [
            (
                10,
                self._sync_dynamic_line(
                    existing_key_fname="term_key",
                    needed_vals_fname="needed_terms",
                    needed_dirty_fname="needed_terms_dirty",
                    line_type="payment_term",
                    container=invoice_container,
                ),
            ),
            (20, self._sync_unbalanced_lines(misc_container)),
            (30, self._sync_rounding_lines(invoice_container)),
            (
                40,
                self._sync_dynamic_line(
                    existing_key_fname="discount_allocation_key",
                    needed_vals_fname="line_ids.discount_allocation_needed",
                    needed_dirty_fname="line_ids.discount_allocation_dirty",
                    line_type="discount",
                    container=invoice_container,
                ),
            ),
            (50, self._sync_tax_lines(tax_container)),
            (60, self._sync_non_deductible_base_lines(invoice_container)),
            (
                70,
                self._sync_dynamic_line(
                    existing_key_fname="epd_key",
                    needed_vals_fname="line_ids.epd_needed",
                    needed_dirty_fname="line_ids.epd_dirty",
                    line_type="epd",
                    container=invoice_container,
                ),
            ),
            (80, self._sync_invoice(invoice_container)),
        ]

        return stack, update_containers

    @contextmanager
    def _sync_dynamic_lines(self, container):
        with self._disable_recursion("skip_invoice_sync") as disabled:
            if disabled:
                yield
                return

            stack_list, update_containers = self._get_sync_stack(container)
            update_containers()
            with ExitStack() as stack:
                stack_list.sort(key=lambda item: item[0])
                for _seq, contextmgr in stack_list:
                    stack.enter_context(contextmgr)

                line_container = {"records": container["records"].line_ids}
                with container["records"].line_ids._sync_invoice(line_container):
                    yield  # noqa: RUF075 - deliberate: on exception the transaction aborts/rolls back, so skipping this sync's post-yield step changes nothing that would otherwise persist
                    line_container["records"] = container["records"].line_ids
                update_containers()
