from datetime import timedelta

from odoo import api, fields, models


class IrAccessException(models.Model):
    _name = "ir.access.exception"
    _inherit = ["ir.access.exception", "mixin.mail.thread", "mixin.mail.activity"]

    date_reminded = fields.Datetime(
        string="Reviewers Reminded",
        copy=False,
        readonly=True,
    )

    @api.model
    def _cron_remind_lapsing(self, days: int = 7) -> None:
        now = fields.Datetime.now()
        lapsing = self.search(
            [
                ("state", "in", ["active"]),
                ("date_to", "<=", now + timedelta(days=days)),
                ("date_reminded", "=", False),
            ]
        )
        for exception in lapsing:
            for reviewer in exception.reviewer_ids:
                exception.activity_schedule(
                    "mail.mail_activity_data_todo",
                    date_deadline=fields.Date.to_date(exception.date_to),
                    summary=self.env._(
                        "Renew or let lapse: %(user)s's exception",
                        user=exception.user_id.name,
                    ),
                    note=exception.reason,
                    user_id=reviewer.id,
                )
        lapsing.date_reminded = now
