from datetime import datetime, time
from typing import Any

from dateutil.relativedelta import relativedelta
from pytz import timezone, utc

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Datetime
from odoo.models import ValuesType


class ResourceCalendarLeaves(models.Model):
    _name = "resource.calendar.leaves"
    _description = "Resource Time Off Detail"
    _order = "date_from"

    name = fields.Char("Reason")
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        readonly=True,
        default=lambda self: self.env.company,
        compute="_compute_company_id",
        store=True,
    )
    calendar_id = fields.Many2one(
        "resource.calendar",
        "Working Hours",
        compute="_compute_calendar_id",
        store=True,
        readonly=False,
        domain="[('company_id', 'in', [company_id, False])]",
        check_company=True,
        index=True,
    )
    resource_id = fields.Many2one(
        "resource.resource",
        "Resource",
        index=True,
        help="If empty, this is a generic time off for the company. If a resource is set, the time off is only for this resource",
    )
    time_type = fields.Selection(
        [("leave", "Time Off"), ("other", "Other")],
        default="leave",
        help="Whether this should be computed as a time off or as work time (eg: formation)",
    )
    date_from = fields.Datetime("Start Date", required=True)
    date_to = fields.Datetime(
        "End Date",
        compute="_compute_date_to",
        readonly=False,
        required=True,
        store=True,
        precompute=True,
    )

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        if self.filtered(lambda leave: leave.date_from > leave.date_to):
            raise ValidationError(
                self.env._(
                    "The start date of the time off must be earlier than the end date."
                )
            )

    @api.model
    def default_get(self, fields: list[str]) -> dict[str, Any]:
        res = super().default_get(fields)
        if (
            "date_from" in fields
            and "date_to" in fields
            and not res.get("date_from")
            and not res.get("date_to")
        ):
            # Then we give the current day and we search the begin and end hours for this day in resource.calendar of the current company
            today = Datetime.now()
            calendar = self.env.company.resource_calendar_id
            if "calendar_id" in res:
                calendar = self.env["resource.calendar"].browse(res["calendar_id"])
            tz = timezone(calendar.tz or "UTC")
            date_from = tz.localize(datetime.combine(today, time.min))
            date_to = tz.localize(datetime.combine(today, time.max))
            res.update(
                date_from=date_from.astimezone(utc).replace(tzinfo=None),
                date_to=date_to.astimezone(utc).replace(tzinfo=None),
            )
        return res

    @api.depends("resource_id.calendar_id")
    def _compute_calendar_id(self):
        for leave in self.filtered("resource_id"):
            leave.calendar_id = leave.resource_id.calendar_id

    @api.depends("calendar_id", "resource_id.company_id")
    def _compute_company_id(self):
        # The resource's company beats env.company: a leave created for a
        # resource of company B while acting in company A must belong to B,
        # or B's users cannot even see it (multi-company rule).
        for leave in self:
            leave.company_id = (
                leave.calendar_id.company_id
                or leave.resource_id.company_id
                or self.env.company
            )

    @api.depends("date_from")
    def _compute_date_to(self):
        # Resolve the reference timezone *per leave*: the acting user's tz (or an
        # explicit context tz) wins, otherwise fall back to this leave's own
        # calendar.  The previous single ``self.company_id.resource_calendar_id``
        # lookup was a multi-record hazard (``Expected singleton`` for a batch
        # spanning several companies) and, during ``precompute`` on create,
        # ``company_id`` still holds its default (``env.company``) rather than the
        # leave's real company — so it end-dated every leave in the wrong tz.  The
        # leave's own ``calendar_id`` is provided in vals and carries a required
        # ``tz``, making it the reliable, correct source.
        user_tz_name = self.env.user.tz or self.env.context.get("tz")
        for leave in self:
            if not leave.date_from or (
                leave.date_to and leave.date_to > leave.date_from
            ):
                continue
            tz_name = (
                user_tz_name
                or leave.calendar_id.tz
                or leave.company_id.resource_calendar_id.tz
                or "UTC"
            )
            local_date_from = utc.localize(leave.date_from).astimezone(
                timezone(tz_name)
            )
            local_date_to = local_date_from + relativedelta(
                hour=23, minute=59, second=59
            )
            leave.date_to = local_date_to.astimezone(utc).replace(tzinfo=None)

    def _copy_leave_vals(self) -> ValuesType:
        self.ensure_one()
        return {
            "name": self.name,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "time_type": self.time_type,
        }
