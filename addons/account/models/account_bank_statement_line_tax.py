from odoo import Command, models


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    def _prepare_for_tax_lines_recomputation(self):
        _liquidity_lines, _suspense_lines, other_lines = self._seek_for_lines()
        other_lines = other_lines.filtered(lambda line: not line.reconciled_lines_ids)

        base_amls = other_lines.filtered(lambda line: not line.tax_repartition_line_id)
        base_lines = [
            self._prepare_base_line_for_taxes_computation(line) for line in base_amls
        ]
        tax_amls = other_lines - base_amls
        tax_lines = [
            self._prepare_tax_line_for_taxes_computation(line) for line in tax_amls
        ]
        return base_lines, tax_lines

    def _create_tax_lines(self, original_base_lines, original_tax_lines, new_lines):
        self.check_singleton()
        liquidity_lines, _suspense_lines, other_lines = self._seek_for_lines()

        original_base_lines, original_tax_lines = self._recompute_tax_lines(
            original_base_lines, original_tax_lines
        )
        original_base_lines += [
            self._prepare_base_line_for_taxes_computation(move_line)
            for move_line in new_lines
        ]

        self._post_recompute_tax_lines(
            original_base_lines, liquidity_lines, original_tax_lines, other_lines
        )

    def _edit_tax_lines(
        self, original_base_lines, original_tax_lines, edited_line, old_move_line
    ):
        self.check_singleton()
        liquidity_lines, _suspense_lines, other_lines = self._seek_for_lines()

        original_base_lines, original_tax_lines = self._recompute_tax_lines(
            original_base_lines, original_tax_lines
        )

        edit_base_line = self._prepare_base_line_for_taxes_computation(edited_line)
        base_lines = []
        for base_line in original_base_lines:
            original_price_unit = base_line["price_unit"]
            base_line["price_unit"] += sum(
                tax_data["tax_amount_currency"]
                for tax_data in base_line["tax_details"]["taxes_data"]
            )
            if base_line["record"] != old_move_line:
                base_lines.append(base_line)
                continue

            price_unit_modified = (
                self.currency_id.compare_amounts(
                    edit_base_line["price_unit"], original_price_unit
                )
                != 0
            )
            if base_line["tax_ids"] and not price_unit_modified:
                edit_base_line["price_unit"] = base_line["price_unit"]

            base_lines.append(edit_base_line)

        self._post_recompute_tax_lines(
            base_lines, liquidity_lines, original_tax_lines, other_lines
        )

    def _remove_tax_lines(
        self, original_base_lines, original_tax_lines, move_line_to_remove
    ):
        self.check_singleton()
        liquidity_lines, _suspense_lines, other_lines = self._seek_for_lines()

        original_base_lines, original_tax_lines = self._recompute_tax_lines(
            original_base_lines, original_tax_lines
        )
        base_lines = []
        for base_line in original_base_lines:
            if base_line["record"] == move_line_to_remove:
                continue

            base_line["price_unit"] += sum(
                tax_data["tax_amount_currency"]
                for tax_data in base_line["tax_details"]["taxes_data"]
            )
            base_lines.append(base_line)

        self._post_recompute_tax_lines(
            base_lines, liquidity_lines, original_tax_lines, other_lines
        )

    def _recompute_tax_lines(self, original_base_lines=None, original_tax_lines=None):
        self.check_singleton()
        if original_base_lines is None and original_tax_lines is None:
            original_base_lines, original_tax_lines = (
                self._prepare_for_tax_lines_recomputation()
            )

        AccountTax = self.env["account.tax"]
        AccountTax._add_tax_details_in_base_lines(original_base_lines, self.company_id)
        AccountTax._round_base_lines_tax_details(
            original_base_lines, self.company_id, tax_lines=original_tax_lines
        )

        return original_base_lines, original_tax_lines

    def _post_recompute_tax_lines(
        self, base_lines, liquidity_lines, original_tax_lines, other_lines
    ):
        self.check_singleton()
        AccountTax = self.env["account.tax"]
        AccountTax._add_tax_details_in_base_lines(base_lines, self.company_id)
        AccountTax._round_base_lines_tax_details(base_lines, self.company_id)
        AccountTax._add_accounting_data_in_base_lines_tax_details(
            base_lines, self.company_id, include_caba_tags=True
        )
        tax_results = AccountTax._prepare_tax_lines(
            base_lines, self.company_id, tax_lines=original_tax_lines
        )

        lines_to_delete = self.env["account.move.line"]
        lines_to_add_or_update = []

        for base_line, to_update in tax_results["base_lines_to_update"]:
            line = base_line["record"]
            line_values = {
                "amount_currency": to_update["amount_currency"],
                "balance": self._prepare_counterpart_amounts_using_st_line_rate(
                    line.currency_id,
                    line.amount_residual or line.balance,
                    to_update["amount_currency"],
                )["balance"],
                "tax_tag_ids": to_update["tax_tag_ids"],
            }
            if line.reconciled_lines_ids:
                line_values["reconciled_lines_ids"] = [
                    Command.set(line.reconciled_lines_ids.ids)
                ]
            lines_to_delete += line
            lines_to_add_or_update.append(line._get_aml_values(**line_values))

        for tax_line_vals in tax_results["tax_lines_to_delete"]:
            lines_to_delete += tax_line_vals["record"]

        for tax_line_vals in tax_results["tax_lines_to_add"]:
            lines_to_add_or_update.append(self._lines_prepare_tax_line(tax_line_vals))  # noqa: PERF401

        for tax_line_vals, grouping_key, to_update in tax_results[
            "tax_lines_to_update"
        ]:
            lines_to_delete += tax_line_vals["record"]
            new_line_vals = self._lines_prepare_tax_line({**grouping_key, **to_update})
            lines_to_add_or_update.append(
                tax_line_vals["record"]._get_aml_values(**new_line_vals)
            )

        lines_to_keep = (liquidity_lines + other_lines) - lines_to_delete
        self._set_move_line_to_statement_line_move(
            lines_to_keep, lines_to_add_or_update
        )

    def _lines_prepare_tax_line(self, tax_line_vals):
        self.check_singleton()

        tax_rep = self.env["account.tax.repartition.line"].browse(
            tax_line_vals["tax_repartition_line_id"]
        )
        name = tax_rep.tax_id.name
        if self.payment_ref:
            name = f"{name} - {self.payment_ref}"
        currency = self.env["res.currency"].browse(tax_line_vals["currency_id"])
        amount_currency = tax_line_vals["amount_currency"]
        balance = self._prepare_counterpart_amounts_using_st_line_rate(
            currency, None, amount_currency
        )["balance"]

        return {
            "account_id": tax_line_vals["account_id"],
            "date": self.date,
            "name": name,
            "partner_id": tax_line_vals["partner_id"],
            "currency_id": currency.id,
            "amount_currency": amount_currency,
            "balance": balance,
            "analytic_distribution": tax_line_vals["analytic_distribution"],
            "tax_repartition_line_id": tax_rep.id,
            "tax_ids": tax_line_vals["tax_ids"],
            "tax_tag_ids": tax_line_vals["tax_tag_ids"],
            "group_tax_id": tax_line_vals["group_tax_id"],
        }

    def _prepare_base_line_for_taxes_computation(self, line_vals):
        self.check_singleton()
        if not line_vals:
            return {}
        tax_type = line_vals.tax_ids.mapped("type_tax_use")
        if "sale" in tax_type and "purchase" in tax_type:
            tax_type = "sale"
        else:
            tax_type = line_vals.tax_ids[0].type_tax_use if line_vals.tax_ids else None
        is_refund = (tax_type == "sale" and line_vals.balance > 0.0) or (
            tax_type == "purchase" and line_vals.balance < 0.0
        )

        return self.env["account.tax"]._prepare_base_line_for_taxes_computation(
            line_vals,
            price_unit=line_vals.amount_currency,
            quantity=1.0,
            is_refund=is_refund,
            special_mode="total_included",
        )

    def _prepare_tax_line_for_taxes_computation(self, line):
        self.check_singleton()
        if not line:
            return {}
        return self.env["account.tax"]._prepare_tax_line_for_taxes_computation(line)
