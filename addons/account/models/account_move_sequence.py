"""Sequence and payment-reference logic for account.move."""

# The entry name is a sequence.mixin sequence, not a plain ir.sequence: the
# prefix/number split, the reset period, the gap bookkeeping and the structured
# payment reference all hang off it. Extracted from account_move.py, which is
# where the rest of the model lives; no method here is overridden by another
# module of this addon.

import calendar
import re
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools import date_utils

from odoo.addons.account.tools import format_structured_reference_iso


class AccountMove(models.Model):
    _inherit = "account.move"

    def _must_check_constrains_date_sequence(self):
        # OVERRIDES sequence.mixin
        return self.state == "posted" and not self.quick_edit_mode

    def _get_last_sequence_domain(self, relaxed=False):
        # pylint: disable=sql-injection
        # EXTENDS account sequence.mixin
        self.ensure_one()
        if not self.date or not self.journal_id:
            return "WHERE FALSE", {}
        where_string = "WHERE journal_id = %(journal_id)s AND name != '/'"
        param = {"journal_id": self.journal_id.id}
        is_payment = self.origin_payment_id or self.env.context.get("is_payment")

        if not relaxed:
            domain = [
                ("journal_id", "=", self.journal_id.id),
                ("id", "!=", self.id or self._origin.id),
                ("name", "not in", ("/", "", False)),
            ]
            if self.journal_id.refund_sequence:
                refund_types = ("out_refund", "in_refund")
                domain += [
                    (
                        "move_type",
                        "in" if self.move_type in refund_types else "not in",
                        refund_types,
                    )
                ]
            if self.journal_id.payment_sequence:
                domain += [("origin_payment_id", "!=" if is_payment else "=", False)]
            if self.journal_id.is_self_billing:
                if self.partner_id:
                    domain += [
                        (
                            "commercial_partner_id",
                            "=",
                            self.partner_id.commercial_partner_id.id,
                        )
                    ]
                else:
                    # If the partner id is not set, we can't compute the sequence, so we force a sequence reset.
                    domain += [(0, "=", 1)]
            reference_move_name = (
                self.sudo()
                .search(
                    domain + [("date", "<=", self.date)], order="date desc", limit=1
                )
                .name
            )
            if not reference_move_name:
                reference_move_name = (
                    self.sudo().search(domain, order="date asc", limit=1).name
                )
            sequence_number_reset = self._deduce_sequence_number_reset(
                reference_move_name
            )
            date_start, date_end, *_ = self._get_sequence_date_range(
                sequence_number_reset
            )
            where_string += """ AND date BETWEEN %(date_start)s AND %(date_end)s"""
            param["date_start"] = date_start
            param["date_end"] = date_end

            # Some regex are catching more sequence formats than we want, so we
            # need to exclude them:
            #
            #                    |                 Regex type                                 |
            # Move Name Format   | Fixed | Yearly | Monthly | Year Range | Year range Monthly |
            # ------------------ | ----- | ------ | ------- | ---------- | ------------------ |
            # Fixed              |   X   |        |         |            |                    |
            # Yearly             |   X   |   X    |         |            |                    |
            # Monthly            |   X   |   X    |    X    |     X      |                    |
            # Year Range         |   X   |   X    |         |     X      |                    |
            # Year range Monthly |   X   |   X    |    X    |     X      |          X         |
            if sequence_number_reset in ("year", "year_range"):
                param["anti_regex"] = (
                    self._make_regex_non_capturing(
                        self._sequence_monthly_regex.split("(?P<seq>")[0]
                    )
                    + "$"
                )
            elif sequence_number_reset == "never":
                # Excluding yearly will also exclude "monthly", "year range" and
                # "year range monthly"
                param["anti_regex"] = (
                    self._make_regex_non_capturing(
                        self._sequence_yearly_regex.split("(?P<seq>")[0]
                    )
                    + "$"
                )

            if (
                param.get("anti_regex")
                and not self.journal_id.sequence_override_regex
                and not self.env.context.get("no_anti_regex")
            ):
                where_string += " AND sequence_prefix !~ %(anti_regex)s "

        if self.journal_id.refund_sequence:
            if self.move_type in ("out_refund", "in_refund"):
                where_string += " AND move_type IN ('out_refund', 'in_refund') "
            else:
                where_string += " AND move_type NOT IN ('out_refund', 'in_refund') "
        elif self.journal_id.payment_sequence:
            if is_payment:
                where_string += " AND origin_payment_id IS NOT NULL "
            else:
                where_string += " AND origin_payment_id IS NULL "

        if self.journal_id.is_self_billing:
            if self.partner_id:
                where_string += " AND commercial_partner_id = %(partner_id)s "
                param["partner_id"] = self.partner_id.commercial_partner_id.id
            else:
                where_string += " AND false "
        return where_string, param

    def _get_starting_sequence(self):
        # EXTENDS account sequence.mixin
        self.ensure_one()
        move_date = self.date or self.invoice_date or fields.Date.context_today(self)
        year_part = "%04d" % move_date.year
        last_day = int(self.company_id.fiscalyear_last_day)
        last_month = int(self.company_id.fiscalyear_last_month)
        is_staggered_year = last_month != 12 or last_day != 31
        if is_staggered_year:
            max_last_day = calendar.monthrange(move_date.year, last_month)[1]
            last_day = min(last_day, max_last_day)
            if move_date > date(move_date.year, last_month, last_day):
                year_part = "%s-%s" % (
                    move_date.strftime("%y"),
                    (move_date + relativedelta(years=1)).strftime("%y"),
                )
            else:
                year_part = "%s-%s" % (
                    (move_date + relativedelta(years=-1)).strftime("%y"),
                    move_date.strftime("%y"),
                )
        # Arbitrarily use annual sequence for sales documents, but monthly
        # sequence for other documents
        if self.journal_id.type in ["sale", "bank", "cash", "credit"]:
            # We reduce short code to 4 characters (0000) in case of staggered
            # year to avoid too long sequences (see Indian GST rule 46(b) for
            # example). Note that it's already the case for monthly sequences.
            starting_sequence = "%s/%s/%s" % (
                self.journal_id.code,
                year_part,
                "0000" if is_staggered_year else "00000",
            )
        elif self.journal_id.is_self_billing:
            partner_identifier = (
                str(self.partner_id.commercial_partner_id.id)
                if self.partner_id
                else _("[Partner id]")
            )
            starting_sequence = "%s%s/%s/%02d/0000" % (
                self.journal_id.code,
                partner_identifier.zfill(5),
                year_part,
                move_date.month,
            )
        else:
            starting_sequence = "%s/%s/%02d/0000" % (
                self.journal_id.code,
                year_part,
                move_date.month,
            )

        if self.journal_id.refund_sequence and self.move_type in (
            "out_refund",
            "in_refund",
        ):
            starting_sequence = "R" + starting_sequence
        if (
            self.journal_id.payment_sequence and self.origin_payment_id
        ) or self.env.context.get("is_payment"):
            starting_sequence = "P" + starting_sequence
        return starting_sequence

    def _get_sequence_date_range(self, reset):
        if reset not in ("year_range", "year_range_month"):
            return super()._get_sequence_date_range(reset)

        fiscalyear_last_day = self.company_id.fiscalyear_last_day
        fiscalyear_last_month = int(self.company_id.fiscalyear_last_month)
        date_start, date_end = date_utils.get_fiscal_year(
            self.date, day=fiscalyear_last_day, month=fiscalyear_last_month
        )

        if reset == "year_range":
            return (date_start, date_end) + (None, None)

        forced_year_range = (date_start.year, date_end.year)
        month_range = date_utils.get_month(self.date)
        fiscalyear_last_month_max_day = calendar.monthrange(
            self.date.year, fiscalyear_last_month
        )[1]
        # We need to truncate the month if:
        # - the fiscal year does not end on the last day of the month
        # - and the move date is part of that month
        # The sequence date range will be something like 2020-11-01 to
        # 2020-11-30. But the sequence should be 2019-2020/11/0001 (or
        # 2020-2021/11/0001), not 2020-2020/11/0001.
        if (
            fiscalyear_last_day < fiscalyear_last_month_max_day
            and fiscalyear_last_month == self.date.month
        ):
            if self.date.day <= fiscalyear_last_day:
                return (
                    month_range[0],
                    month_range[1].replace(day=fiscalyear_last_day),
                ) + forced_year_range
            else:
                return (
                    month_range[0].replace(day=fiscalyear_last_day + 1),
                    month_range[1],
                ) + forced_year_range
        else:
            return month_range + forced_year_range

    # -------------------------------------------------------------------------
    # PAYMENT REFERENCE
    # -------------------------------------------------------------------------

    def _get_invoice_reference_euro_invoice(self):
        """Compute the reference based on the RF Creditor Reference.
        The data of the reference is the journal short code and the database
        id number of the invoice. For instance, if a journal code is INV and
        an invoice is issued with id 37, the check number is 67 so the
        reference will be 'RF67 INV0 0003 7'.
        """
        self.ensure_one()
        journal_identifier = (
            self.journal_id.code
            if self.journal_id.code.isascii() and self.journal_id.code.isalnum()
            else self.journal_id.id
        )
        return format_structured_reference_iso(
            f"{journal_identifier}{str(self.id).zfill(6)}"
        )

    def _get_invoice_reference_euro_partner(self):
        """Compute the reference based on the RF Creditor Reference.
        The data of the reference is the user defined reference of the
        partner or the database id number of the parter.
        For instance, if an invoice is issued for the partner with internal
        reference 'food buyer 654', the digits will be extracted and used as
        the data. This will lead to a check number equal to 00 and the
        reference will be 'RF00 654'.
        If no reference is set for the partner, its id in the database will
        be used.
        """
        self.ensure_one()
        journal_identifier = (
            self.journal_id.code
            if self.journal_id.code.isascii() and self.journal_id.code.isalnum()
            else self.journal_id.id
        )
        partner_ref = self.partner_id.ref
        partner_ref_nr = (
            re.sub(r"\D", "", partner_ref or "")[-21:] or str(self.partner_id.id)[-21:]
        )
        partner_ref_nr = f"{journal_identifier}{partner_ref_nr}"[-21:]
        return format_structured_reference_iso(partner_ref_nr)

    def _get_invoice_reference_number_invoice(self):
        """Return the digits extracted from the Odoo-format invoice reference
        (the journal sequence number), stripping any non-digit characters.
        """
        ref = self._get_invoice_reference_odoo_invoice() or ""
        return "".join(char for char in ref if char.isdigit())

    def _get_invoice_reference_number_partner(self):
        """Compute the reference based on the Number format.
        The data used is the reference set on the partner or its database
        id otherwise. For instance if the reference of the customer is
        'customer 97', the reference will be '97'.
        """
        ref = self._get_invoice_reference_odoo_partner()
        return "".join(char for char in ref if char.isdigit())

    def _get_invoice_reference_odoo_invoice(self):
        """Return self.name, the invoice number generated by the journal sequence."""
        self.ensure_one()
        return self.name

    def _get_invoice_reference_odoo_partner(self):
        """Compute the reference based on the Odoo format.
        The data used is the reference set on the partner or its database
        id otherwise. For instance if the reference of the customer is
        'dumb customer 97', the reference will be 'CUST/dumb customer 97'.
        """
        ref = self.partner_id.ref or str(self.partner_id.id)
        prefix = _("CUST")
        return "%s/%s" % (prefix, ref)

    def _get_invoice_computed_reference(self):
        self.ensure_one()
        ref_function = getattr(
            self,
            f"_get_invoice_reference_{self.journal_id.invoice_reference_model}_{self.journal_id.invoice_reference_type}",
            None,
        )
        if ref_function is None:
            raise UserError(
                _(
                    "The combination of reference model and reference type on the journal is not implemented"
                )
            )
        return ref_function()
