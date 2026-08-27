from dateutil.relativedelta import relativedelta

from odoo import api, models


class AccountMove(models.Model):
    _inherit = "account.move"

    @api.model
    def _apply_delta_recurring_entries(self, date, date_origin, period):
        deltas = {"monthly": 1, "quarterly": 3, "yearly": 12}
        prev_months = (
            (date.year - date_origin.year) * 12 + date.month - date_origin.month
        )
        return date_origin + relativedelta(months=deltas[period] + prev_months)

    def _copy_recurring_entries(self):
        for record in self:
            record.auto_post_origin_id = record.auto_post_origin_id or record
            next_date = self._apply_delta_recurring_entries(
                record.date, record.auto_post_origin_id.date, record.auto_post
            )

            if not record.auto_post_until or next_date <= record.auto_post_until:
                record.copy(
                    default=record._get_fields_to_copy_recurring_entries(
                        {"date": next_date}
                    )
                )

    def _get_fields_to_copy_recurring_entries(self, values):
        values.update(
            {
                "auto_post": self.auto_post,
                "auto_post_until": self.auto_post_until,
                "auto_post_origin_id": self.auto_post_origin_id.id,
                "invoice_user_id": self.invoice_user_id.id,
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
            values.update(
                {
                    "invoice_date_due": values["date"]
                    + (self.invoice_date_due - self.date)
                }
            )
        return values
