from datetime import timedelta

from pytz import utc

from odoo import models
from odoo.tools.date_utils import localized, sum_intervals


class ResourceSchedulingTools(models.AbstractModel):
    """Calendar-aware scheduling helpers shared by scheduling consumers.

    These methods translate between wall-clock datetimes and *working* time
    (hours that respect a resource calendar, its leaves and flexible-hours
    rules).  They are independent of any field-name convention — callers pass
    the datetimes/resource/calendar explicitly — which is why they live in a
    standalone abstract model rather than on either concrete consumer.

    Inherited by:
    - :class:`resource.scheduling.mixin` (and, through it, every consumer such
      as ``project.task``)
    - :class:`resource.reservation` (which must compute its own committed hours
      without depending on the mixin)

    Keeping a single implementation here avoids the two copies drifting apart.
    """

    _name = "resource.scheduling.tools"
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
        """Compute working hours between two datetimes using the resource calendar.

        Handles timezone conversion, flexible resources, regular resources,
        and no-resource fallback (raw timedelta).

        :param date_start: datetime (naive = UTC assumed, or timezone-aware)
        :param date_end: datetime
        :param resource: optional ``resource.resource`` singleton
        :param calendar: optional ``resource.calendar`` (overrides resource's)
        :param compute_leaves: whether to subtract leaves (default True)
        :param leave_domain: optional domain for leave filtering
        :return: float (hours)
        """
        self.ensure_one()
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

        if resource._is_flexible():
            work_intervals, hours_per_day, hours_per_week = (
                resource._get_flexible_resource_valid_work_intervals(start_utc, end_utc)
            )
            return resource._get_flexible_resource_work_hours(
                work_intervals[resource.id],
                hours_per_day[resource.id],
                hours_per_week[resource.id],
            )

        work_intervals, _calendar_intervals = resource._get_valid_work_intervals(
            start_utc,
            end_utc,
            calendars=(calendar,) if calendar else None,
        )
        return sum_intervals(work_intervals[resource.id])

    def _scheduling_snap_to_calendar(self, date_start, date_end, calendar=None):
        """Snap start/end to the nearest work interval boundaries.

        :param date_start: datetime
        :param date_end: datetime
        :param calendar: optional ``resource.calendar`` override
        :return: tuple ``(snapped_start, snapped_end)`` as naive UTC datetimes
        """
        self.ensure_one()
        cal = calendar or self._scheduling_resolve_calendar()
        if not cal or not date_start or not date_end:
            return date_start, date_end

        start_utc = localized(date_start)
        end_utc = localized(date_end)

        intervals = cal._work_intervals_batch(start_utc, end_utc)[False]
        if not intervals:
            return date_start, date_end

        items = list(intervals)
        snapped_start = items[0][0].astimezone(utc).replace(tzinfo=None)
        snapped_end = items[-1][1].astimezone(utc).replace(tzinfo=None)
        return snapped_start, snapped_end

    def _scheduling_plan_hours(
        self,
        hours,
        date_start,
        resource=None,
        calendar=None,
        leave_domain=None,
    ):
        """Compute end datetime by planning forward N working hours from start.

        Inverse of ``_scheduling_get_work_hours``.

        :param hours: float — working hours to plan (0 returns ``date_start``)
        :param date_start: datetime — start point
        :param resource: optional ``resource.resource`` singleton
        :param calendar: optional ``resource.calendar`` override
        :param leave_domain: optional domain for leave filtering
        :return: datetime (end, naive UTC) or ``False`` if hours can't be planned
        """
        self.ensure_one()
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
            return result.astimezone(utc).replace(tzinfo=None)
        return False

    def _scheduling_resolve_calendar(self, resource=None):
        """Resolve the best calendar for this record.

        Resolution order:
        1. resource's calendar (if resource provided)
        2. record's ``resource_calendar_id`` field (if present on model)
        3. record's ``company_id`` calendar (if ``company_id`` field exists)
        4. current company's calendar
        """
        self.ensure_one()
        if resource and resource.calendar_id:
            return resource.calendar_id
        if "resource_calendar_id" in self._fields and self.resource_calendar_id:
            return self.resource_calendar_id
        if "company_id" in self._fields and self.company_id:
            return self.company_id.resource_calendar_id
        return self.env.company.resource_calendar_id
