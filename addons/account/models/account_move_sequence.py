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
        return self.state == "posted" and not self.quick_edit_mode

    def _get_last_sequence_domain(self, relaxed=False):
        # pylint: disable=sql-injection
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

            if sequence_number_reset in ("year", "year_range"):
                param["anti_regex"] = (
                    self._prepare_regex_non_capturing(
                        self._sequence_monthly_regex.split("(?P<seq>")[0]
                    )
                    + "$"
                )
            elif sequence_number_reset == "never":
                param["anti_regex"] = (
                    self._prepare_regex_non_capturing(
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
        if self.journal_id.type in ["sale", "bank", "cash", "credit"]:
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


    def _get_invoice_reference_euro_invoice(self):
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
        ref = self._get_invoice_reference_odoo_invoice() or ""
        return "".join(char for char in ref if char.isdigit())

    def _get_invoice_reference_number_partner(self):
        ref = self._get_invoice_reference_odoo_partner()
        return "".join(char for char in ref if char.isdigit())

    def _get_invoice_reference_odoo_invoice(self):
        self.ensure_one()
        return self.name

    def _get_invoice_reference_odoo_partner(self):
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
