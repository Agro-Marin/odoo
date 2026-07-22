# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import datetime, timedelta

from pytz import timezone, utc

from odoo import api, models


class ResourceCalendarLeaves(models.Model):
    _inherit = "resource.calendar.leaves"

    @api.depends("date_from")
    def _compute_calendar_id(self):
        def date2datetime(date, tz):
            dt = datetime.fromordinal(date.toordinal())
            return tz.localize(dt).astimezone(utc).replace(tzinfo=None)

        leaves_by_contract = self.grouped(
            lambda leave: leave.resource_id.employee_id.version_id
        )
        # set aside leaves without version_id for super
        remaining = leaves_by_contract.pop(
            self.env["hr.version"],
            self.env["resource.calendar.leaves"],
        )
        for contract, leaves in leaves_by_contract.items():
            tz = timezone(contract.resource_calendar_id.tz or "UTC")
            start_dt = date2datetime(contract.date_start, tz)
            # ``date_end`` is the version's *inclusive* last valid day (see
            # hr.version._compute_dates: date_end = next_date_version - 1 day), so
            # the exclusive upper bound is midnight of the following day. Using
            # midnight of ``date_end`` itself dropped every leave falling on that
            # last day (it matched neither this version's window nor the next),
            # leaving those leaves with no calendar assigned.
            end_dt = (
                date2datetime(contract.date_end + timedelta(days=1), tz)
                if contract.date_end
                else datetime.max  # noqa: DTZ901 - naive sentinel, compared only
                # against other naive datetimes (date2datetime always strips
                # tzinfo, Odoo Datetime fields are always naive); see
                # hr_attendance_gantt/hr_work_entry_attendance/calendar
                # precedent from this campaign.
            )
            # only modify leaves that fall under the active contract
            # B023: lambdas reference loop variables `start_dt`/`end_dt` but
            # are invoked eagerly on this statement (result's .calendar_id is
            # set within this same iteration) - no late-binding risk.
            leaves.filtered(
                lambda leave: leave.date_from and start_dt <= leave.date_from < end_dt  # noqa: B023
            ).calendar_id = contract.resource_calendar_id

        super(ResourceCalendarLeaves, remaining)._compute_calendar_id()
