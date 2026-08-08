"""Recurring-entry duplication for account.move."""

# Auto-posted recurring entries are produced by copying a template move forward
# in time; this is the date arithmetic and the field-copy policy for that copy.
# Extracted from account_move.py.

from dateutil.relativedelta import relativedelta

from odoo import api, models


class AccountMove(models.Model):
    _inherit = "account.move"

    @api.model
    def _apply_delta_recurring_entries(self, date, date_origin, period):
        """Advance date by `period` months, keeping the original day of the month if possible."""
        deltas = {"monthly": 1, "quarterly": 3, "yearly": 12}
        prev_months = (
            (date.year - date_origin.year) * 12 + date.month - date_origin.month
        )
        return date_origin + relativedelta(months=deltas[period] + prev_months)

    def _copy_recurring_entries(self):
        """Copy a recurring (periodic) entry and adjust its dates for the next period.
        Meant to be called right after posting a periodic entry.
        Copies extra fields as defined by _get_fields_to_copy_recurring_entries().
        """
        for record in self:
            record.auto_post_origin_id = (
                record.auto_post_origin_id or record
            )  # original entry references itself
            next_date = self._apply_delta_recurring_entries(
                record.date, record.auto_post_origin_id.date, record.auto_post
            )

            if (
                not record.auto_post_until or next_date <= record.auto_post_until
            ):  # recurrence continues
                record.copy(
                    default=record._get_fields_to_copy_recurring_entries(
                        {"date": next_date}
                    )
                )

    def _get_fields_to_copy_recurring_entries(self, values):
        """Determine which extra fields to copy when copying a recurring entry.
        To be extended by modules that add fields with copy=False (implicit or explicit)
        whenever the opposite behavior is expected for recurring invoices.
        """
        values.update(
            {
                "auto_post": self.auto_post,  # copy=False to avoid mistakes but should be the same in recurring copies
                "auto_post_until": self.auto_post_until,  # same as above
                "auto_post_origin_id": self.auto_post_origin_id.id,  # same as above
                "invoice_user_id": self.invoice_user_id.id,  # otherwise user would be OdooBot
            }
        )
        if self.invoice_date:
            values.update(
                {
                    "invoice_date": self._apply_delta_recurring_entries(
                        self.invoice_date,
                        self.auto_post_origin_id.invoice_date,
                        self.auto_post,
                    )
                }
            )
        if not self.invoice_payment_term_id and self.invoice_date_due:
            # no payment terms: maintain timedelta between due date and accounting date
            values.update(
                {
                    "invoice_date_due": values["date"]
                    + (self.invoice_date_due - self.date)
                }
            )
        return values

    # EDI / incoming-document helpers live in account_move_edi.py
