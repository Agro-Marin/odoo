"""Quick-encoding assistance for account.move."""

# Quick edit mode lets an accountant type a bill's total and have the lines
# suggested from what this partner was booked to last time. It is an input
# convenience with no bearing on the posted entry: nothing here runs outside a
# draft the user is typing into. Extracted from account_move.py.

from datetime import date, timedelta

from odoo import api, fields, models
from odoo.fields import Command
from odoo.tools import SQL, float_is_zero


class AccountMove(models.Model):
    _inherit = "account.move"

    @api.model
    def _get_frequent_account_and_taxes(self, company_id, partner_id, move_type):
        """Return the most used accounts and taxes for a given partner and company,
        optionally filtered by move type.
        """
        if not partner_id:
            return 0, False, False
        domain = [
            *self.env["account.move.line"]._check_company_domain(company_id),
            ("partner_id", "=", partner_id),
            ("date", ">=", date.today() - timedelta(days=365 * 2)),
        ]
        if move_type in self.env["account.move"].get_inbound_types(
            include_receipts=True
        ):
            domain.append(("account_id.internal_group", "=", "income"))
        elif move_type in self.env["account.move"].get_outbound_types(
            include_receipts=True
        ):
            domain.append(("account_id.internal_group", "=", "expense"))

        # No bypass_access: the aggregation would leak which accounts/taxes a
        # partner is billed on from move lines the user's record rules hide.
        query = self.env["account.move.line"]._search(domain)
        account_code = self.env["account.account"]._field_to_sql(
            "account_move_line__account_id", "code", query
        )
        rows = self.env.execute_query(
            SQL(
                """
            SELECT COUNT(foo.id), foo.account_id, foo.taxes
              FROM (
                         SELECT account_move_line__account_id.id AS account_id,
                                %(account_code)s AS code,
                                account_move_line.id,
                                ARRAY_AGG(tax_rel.account_tax_id) FILTER (WHERE tax_rel.account_tax_id IS NOT NULL) AS taxes
                           FROM %(from_clause)s
                      LEFT JOIN account_move_line_account_tax_rel tax_rel ON account_move_line.id = tax_rel.account_move_line_id
                          WHERE %(where_clause)s
                       GROUP BY account_move_line__account_id.id,
                                %(account_code)s,
                                account_move_line.id
                   ) AS foo
          GROUP BY foo.account_id, foo.taxes
          ORDER BY COUNT(foo.id) DESC, taxes ASC NULLS LAST
             LIMIT 1
            """,
                account_code=account_code,
                from_clause=query.from_clause,
                where_clause=query.where_clause or SQL("TRUE"),
            )
        )
        return rows[0] if rows else (0, False, False)

    def _get_quick_edit_suggestions(self):
        """Return the suggested values for a new line when quick_edit_total_amount is set,
        computing the price_unit needed to match that total amount.
        If the vendor/customer is set, suggest the most frequently used account for that
        partner as the default; otherwise use the journal default.
        """
        self.ensure_one()
        if not self.quick_edit_mode or not self.quick_edit_total_amount:
            return False
        count, account_id, tax_ids = self._get_frequent_account_and_taxes(
            self.company_id.id,
            self.partner_id.id,
            self.move_type,
        )
        if count:
            taxes = self.env["account.tax"].browse(tax_ids)
        else:
            account_id = self.journal_id.default_account_id.id
            if self.is_sale_document(include_receipts=True):
                taxes = self.journal_id.default_account_id.tax_ids.filtered(
                    lambda tax: tax.type_tax_use == "sale"
                )
            else:
                taxes = self.journal_id.default_account_id.tax_ids.filtered(
                    lambda tax: tax.type_tax_use == "purchase"
                )
            if not taxes:
                taxes = (
                    self.journal_id.company_id.account_sale_tax_id
                    if self.journal_id.type == "sale"
                    else self.journal_id.company_id.account_purchase_tax_id
                )
            taxes = self.fiscal_position_id.map_tax(taxes)

        # When a payment term has an early payment discount with the epd computation set to 'mixed', recomputing
        # the untaxed amount should take in consideration the discount percentage otherwise we'd get a wrong value.
        # We check that we have only one percentage tax as computing from multiple taxes with different types can get complicated.
        # In one example: let's say: base = 100, discount = 2%, tax = 21%
        # the total will be calculated as: total = base + (base * (1 - discount)) * tax
        # If we manipulate the equation to get the base from the total, we'll have base = total / ((1 - discount) * tax + 1)
        term = self.invoice_payment_term_id
        discount_percentage = term.discount_percentage if term.early_discount else 0
        remaining_amount = (
            self.quick_edit_total_amount - self.tax_totals["total_amount_currency"]
        )

        if (
            discount_percentage
            and term.early_pay_discount_computation == "mixed"
            and len(taxes) == 1
            and taxes.amount_type == "percent"
        ):
            price_untaxed = self.currency_id.round(
                remaining_amount
                / (((1.0 - discount_percentage / 100.0) * (taxes.amount / 100.0)) + 1.0)
            )
        else:
            price_untaxed = taxes.with_context(force_price_include=True).compute_all(
                remaining_amount
            )["total_excluded"]
        return {
            "account_id": account_id,
            "tax_ids": taxes.ids,
            "price_unit": price_untaxed,
        }

    @api.onchange("quick_edit_mode", "journal_id", "company_id")
    def _quick_edit_mode_suggest_invoice_date(self):
        """Suggest the Customer Invoice/Vendor Bill date based on previous invoice and lock dates"""
        for record in self:
            if record.quick_edit_mode and not record.invoice_date:
                invoice_date = fields.Date.context_today(self)
                prev_move = self.search(
                    [
                        ("state", "=", "posted"),
                        ("journal_id", "=", record.journal_id.id),
                        ("company_id", "=", record.company_id.id),
                        ("invoice_date", "!=", False),
                    ],
                    limit=1,
                )
                if prev_move:
                    invoice_date = self._get_accounting_date(
                        prev_move.invoice_date, False
                    )
                record.invoice_date = invoice_date

    @api.onchange("quick_edit_total_amount", "partner_id")
    def _onchange_quick_edit_total_amount(self):
        """Create a new line with the suggested values (account, price_unit, and tax)
        such that the total amount matches the quick total amount.
        """
        if (
            not self.quick_edit_total_amount
            or not self.quick_edit_mode
            or len(self.invoice_line_ids) > 0
        ):
            return
        suggestions = self.quick_encoding_vals
        self.invoice_line_ids = [Command.clear()]
        self.invoice_line_ids += self.env["account.move.line"].new(
            {
                "partner_id": self.partner_id,
                "account_id": suggestions["account_id"],
                "currency_id": self.currency_id.id,
                "price_unit": suggestions["price_unit"],
                "tax_ids": [Command.set(suggestions["tax_ids"])],
            }
        )
        self._check_total_amount(self.quick_edit_total_amount)

    @api.onchange("invoice_line_ids")
    def _onchange_quick_edit_line_ids(self):
        quick_encode_suggestion = self.env.context.get("quick_encoding_vals")
        if (
            not self.quick_edit_total_amount
            or not self.quick_edit_mode
            or not self.invoice_line_ids
            or not quick_encode_suggestion
            or quick_encode_suggestion["price_unit"]
            != self.invoice_line_ids[-1].price_unit
        ):
            return
        self._check_total_amount(self.quick_edit_total_amount)

    def _check_total_amount(self, amount_total):
        """Verify that the total amount matches the chosen quick total amount, since
        rounding errors may appear. In that case, round the tax up so the total equals
        the quick total amount set.
        E.g.: 100€ including 21% tax: base = 82.64, tax = 17.35, total = 99.99
        The tax will be set to 17.36 in order to have a total of 100.00
        """
        if not self.tax_totals or not amount_total:
            return
        totals = self.tax_totals
        tax_amount_rounding_error = amount_total - totals["total_amount_currency"]
        if not float_is_zero(
            tax_amount_rounding_error, precision_rounding=self.currency_id.rounding
        ):
            # The base subtotal is always the first one; matching it by its
            # translated label broke under custom tax-group subtotals or a
            # different rendering language. Only force the total when a tax
            # group actually absorbs the delta, otherwise the widget's parts
            # would no longer sum to its total.
            for subtotal in totals["subtotals"][:1]:
                if subtotal["tax_groups"]:
                    subtotal["tax_groups"][0]["tax_amount_currency"] += (
                        tax_amount_rounding_error
                    )
                    totals["total_amount_currency"] = amount_total
                    self.tax_totals = totals
