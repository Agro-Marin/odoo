from datetime import UTC, timedelta

from odoo import models
from odoo.tools.date_utils import localized


class MixinResourceSchedulingTools(models.AbstractModel):
    _name = "mixin.resource.scheduling.tools"
    _description = "Resource Scheduling Helpers"

    def _scheduling_get_work_hours(
        self,
        date_start,
        date_end,
        resource=None,
        calendar=None,
        compute_leaves=True,
        leave_domain=None,
    ):
        self.check_singleton()
        if not date_start or not date_end or date_end <= date_start:
            return 0.0

        start_utc = localized(date_start)
        end_utc = localized(date_end)

        if not resource:
            cal = calendar or self._scheduling_resolve_calendar()
            if cal:
                return cal.get_work_hours_count(
                    start_utc,
                    end_utc,
                    compute_leaves=compute_leaves,
                    domain=leave_domain,
                )
            return (end_utc - start_utc).total_seconds() / 3600.0

        if resource._is_flexible() and calendar and calendar != resource.calendar_id:
            return calendar.get_work_hours_count(
                start_utc,
                end_utc,
                compute_leaves=compute_leaves,
                domain=leave_domain,
            )
        schedule = resource._get_work_schedule(
            start_utc,
            end_utc,
            calendars=(calendar,) if calendar else None,
            compute_leaves=compute_leaves,
            leave_domain=leave_domain,
        )
        return schedule.work_hours(resource)

    def _scheduling_snap_to_calendar(self, date_start, date_end, calendar=None):
        self.check_singleton()
        cal = calendar or self._scheduling_resolve_calendar()
        if not cal or not date_start or not date_end:
            return date_start, date_end

        start_utc = localized(date_start)
        end_utc = localized(date_end)

        intervals = cal._work_intervals_batch(start_utc, end_utc)[False]
        if not intervals:
            return date_start, date_end

        items = list(intervals)
        snapped_start = items[0][0].astimezone(UTC).replace(tzinfo=None)
        snapped_end = items[-1][1].astimezone(UTC).replace(tzinfo=None)
        return snapped_start, snapped_end

    def _scheduling_plan_hours(
        self,
        hours,
        date_start,
        resource=None,
        calendar=None,
        leave_domain=None,
    ):
        self.check_singleton()
        if hours is None or not date_start:
            return False
        if not hours:
            return date_start

        cal = calendar or self._scheduling_resolve_calendar(resource=resource)
        if not cal:
            return date_start + timedelta(hours=hours)

        start_utc = localized(date_start)
        plan_kwargs = {
            "compute_leaves": True,
            "resource": resource,
        }
        if leave_domain is not None:
            plan_kwargs["domain"] = leave_domain
        result = cal.plan_hours(hours, start_utc, **plan_kwargs)
        if result:
            return result.astimezone(UTC).replace(tzinfo=None)
        return False

    def _scheduling_resolve_calendar(self, resource=None):
        self.check_singleton()
        if resource and resource.calendar_id:
            return resource.calendar_id
        if "resource_calendar_id" in self._fields and self.resource_calendar_id:
            return self.resource_calendar_id
        if "company_id" in self._fields and self.company_id:
            return self.company_id.resource_calendar_id
        return self.env.company.resource_calendar_id
