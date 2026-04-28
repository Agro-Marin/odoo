from datetime import timedelta

from pytz import utc

from odoo import api, fields, models
from odoo.tools.date_utils import localized, sum_intervals


class ResourceSchedulingMixin(models.AbstractModel):
    """Consumer-facing mixin for models that delegate scheduling data to resource.reservation.

    Provides:
    - Reverse One2many to ``resource.reservation`` via ``(res_model, res_id)``
    - Shared ``allocated_percentage`` + computed ``allocated_hours``
      and ``schedule_overlap_count``
    - CRUD hooks that reconcile reservations via ``_sync_reservations``
    - Contracts consumers override: ``_get_reservation_date_fields``,
      ``_get_reservation_vals_list``, ``_get_sync_trigger_fields``
    - Utility methods (``_scheduling_get_work_hours``,
      ``_scheduling_plan_hours``, ``_scheduling_snap_to_calendar``,
      ``_scheduling_resolve_calendar``) for calendar-aware computations
      independent of field-name conventions

    Scheduling data fields (date_start, date_end, resource_id,
    resource_calendar_id) live on ``resource.reservation`` itself — consumer
    models expose their own date fields via ``_get_reservation_date_fields``
    and build sync payloads via ``_get_reservation_vals_list``.
    """

    _name = "resource.scheduling.mixin"
    _description = "Resource Scheduling Mixin"

    # ---- Reservation linkage ----
    reservation_ids = fields.One2many(
        "resource.reservation",
        "res_id",
        string="Reservations",
        domain=lambda self: [("res_model", "=", self._name)],
        bypass_search_access=True,
    )

    # ---- Allocation ----
    allocated_percentage = fields.Float(
        "Allocation %",
        default=100.0,
        help="Percentage of the resource's work capacity allocated to this record.",
    )
    allocated_hours = fields.Float(
        "Allocated Hours",
        compute="_compute_allocated_hours",
        store=True,
        readonly=False,
        help="Working hours between scheduling start and end, respecting the resource calendar.",
    )

    # ---- Aggregated conflict count (sums the linked reservations) ----
    schedule_overlap_count = fields.Integer(
        "Scheduling Conflicts",
        compute="_compute_schedule_overlap_count",
    )

    # ------------------------------------------------------------------
    # Contracts (consumers override)
    # ------------------------------------------------------------------

    def _get_reservation_date_fields(self):
        """Return ``(start_field, end_field)`` names, or ``(None, None)``.

        Consumers whose records are never scheduled (no planned dates) keep
        the default.  Consumers with their own date fields override this to
        point at those field names.
        """
        return (None, None)

    def _get_reservation_vals_list(self):
        """Return a list of dicts describing the reservations to keep in sync.

        Each dict describes one reservation and may contain ``name``,
        ``date_start``, ``date_end``, ``resource_id``,
        ``allocated_percentage``, ``enforcement_mode``.  An empty list
        deletes all reservations linked to the record.
        """
        self.ensure_one()
        return []

    def _get_sync_trigger_fields(self):
        """Return the set of field names whose write triggers ``_sync_reservations``.

        Default: the date fields returned by ``_get_reservation_date_fields``.
        Consumers typically add assignee / allocation-percentage fields.
        """
        start_field, end_field = self._get_reservation_date_fields()
        triggers = set()
        if start_field:
            triggers.add(start_field)
        if end_field:
            triggers.add(end_field)
        return triggers

    # ------------------------------------------------------------------
    # Sync logic
    # ------------------------------------------------------------------

    def _sync_reservations(self):
        """Reconcile ``resource.reservation`` records for each consumer record.

        Short-circuits for consumers whose ``_get_reservation_date_fields``
        returns ``(None, None)`` — they never create reservations, so the
        per-record SQL probe is pure overhead on every create/write.
        """
        start_field, end_field = self._get_reservation_date_fields()
        if not start_field or not end_field:
            return
        reservation_model = self.env["resource.reservation"]
        for record in self:
            reservation_model._sync_reservation(
                record, record._get_reservation_vals_list()
            )

    # ------------------------------------------------------------------
    # CRUD hooks (patterned on rating.mixin / mail.thread)
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_reservations()
        return records

    def write(self, vals):
        result = super().write(vals)
        triggers = self._get_sync_trigger_fields()
        if triggers and triggers.intersection(vals.keys()):
            self._sync_reservations()
        if "active" in vals:
            # Mirror archive state: a record's reservations are no longer
            # claims on the resource once the record is archived, and
            # they come back when it is restored.
            self.env["resource.reservation"].sudo().with_context(
                active_test=False
            ).search(
                [
                    ("res_model", "=", self._name),
                    ("res_id", "in", self.ids),
                ]
            ).write({"active": vals["active"]})
        return result

    def unlink(self):
        # Capture ids and model name before super(); the recordset is invalid after.
        model_name, record_ids = self._name, self.ids
        result = super().unlink()
        self.env["resource.reservation"].sudo().search(
            [
                ("res_model", "=", model_name),
                ("res_id", "in", record_ids),
            ]
        ).unlink()
        return result

    # ------------------------------------------------------------------
    # Generic computes
    # ------------------------------------------------------------------

    def _compute_allocated_hours(self):
        """Compute working hours from the consumer's date fields.

        When ``_get_reservation_date_fields`` returns ``(None, None)`` the
        consumer is not calendar-aware at the core level; preserve any
        manually entered value rather than overwriting it with zero.

        Consumers with real date fields typically override this with a
        domain-specific compute (e.g. ``project_enterprise`` uses
        ``planned_date_begin`` / ``date_end`` + assignee calendars).
        """
        for record in self:
            start_field, end_field = record._get_reservation_date_fields()
            if not start_field or not end_field:
                # No scheduling fields: keep the manual value (the field is
                # stored + readonly=False, so direct writes already persist).
                continue
            date_start = record[start_field]
            date_end = record[end_field]
            if not date_start or not date_end:
                record.allocated_hours = 0.0
                continue
            resource = record.resource_id if "resource_id" in record._fields else None
            calendar = (
                record.resource_calendar_id
                if "resource_calendar_id" in record._fields
                else None
            )
            work_hours = record._scheduling_get_work_hours(
                date_start,
                date_end,
                resource=resource,
                calendar=calendar,
            )
            pct = record.allocated_percentage
            record.allocated_hours = round(work_hours * pct / 100.0, 2)

    @api.depends("reservation_ids.schedule_overlap_count")
    def _compute_schedule_overlap_count(self):
        """Aggregate overlap counts from linked reservations."""
        for record in self:
            record.schedule_overlap_count = sum(
                record.reservation_ids.mapped("schedule_overlap_count")
            )

    # ------------------------------------------------------------------
    # Utility methods (calendar-aware, callable on consumer records)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
