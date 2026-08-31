from datetime import UTC, datetime, timedelta

from odoo import api, models
from odoo.libs.datetime import timezone


class ResourceCalendarLeaves(models.Model):
    _inherit = "resource.calendar.leaves"

    @api.depends("date_from")
    def _compute_calendar_id(self):
        def _date_to_datetime(date, tz):
            dt = datetime.fromordinal(date.toordinal())
            return dt.replace(tzinfo=tz).astimezone(UTC).replace(tzinfo=None)

        leaves_by_contract = self.grouped(
            lambda leave: leave.resource_id.employee_id.version_id
        )
        remaining = leaves_by_contract.pop(
            self.env["hr.version"],
            self.env["resource.calendar.leaves"],
        )
        for contract, leaves in leaves_by_contract.items():
            tz = timezone(contract.resource_calendar_id.tz or "UTC")
            start_dt = _date_to_datetime(contract.date_start, tz)
            end_dt = (
                _date_to_datetime(contract.date_end + timedelta(days=1), tz)
                if contract.date_end
                else datetime.max  # noqa: DTZ901 - naive sentinel, compared only
            )
            leaves.filtered(
                lambda leave, start_dt=start_dt, end_dt=end_dt: (
                    leave.date_from and start_dt <= leave.date_from < end_dt
                )
            ).calendar_id = contract.resource_calendar_id

        super(ResourceCalendarLeaves, remaining)._compute_calendar_id()
