from collections import defaultdict
from datetime import timedelta

from pytz import utc

from odoo import api, fields, models
from odoo.exceptions import MissingError, ValidationError
from odoo.libs.intervals import Intervals
from odoo.tools import SQL
from odoo.tools.date_utils import localized, sum_intervals


class ResourceReservation(models.Model):
    """Concrete booking record for any resource over a time window.

    Holds canonical scheduling data (``date_start``, ``date_end``,
    ``resource_id``, ``resource_calendar_id``) locally and an origin
    reference (``res_model`` / ``res_id``) back to the consumer that
    created it (``project.task``, ``room.booking``, ``mrp.workorder``, ...).

    Consumer models own :class:`resource.scheduling.mixin` for the O2M
    linkage and the ``_sync_reservations`` lifecycle; this model stays
    standalone so that all reservations live in one table, enabling
    cross-module conflict detection (e.g. a person double-booked across
    a task and a room).
    """

    _name = "resource.reservation"
    _description = "Resource Reservation"
    _order = "date_start"

    # ---- Identity ----
    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
    )

    # ---- Scheduling date fields ----
    date_start = fields.Datetime(
        "Scheduled Start",
        index=True,
    )
    date_end = fields.Datetime(
        "Scheduled End",
        index=True,
    )

    # ---- Resource & calendar ----
    resource_id = fields.Many2one(
        "resource.resource",
        "Resource",
        index=True,
        help="The resource (person, equipment) assigned to this schedule.",
    )
    resource_calendar_id = fields.Many2one(
        "resource.calendar",
        "Working Calendar",
        compute="_compute_resource_calendar_id",
        store=True,
        readonly=False,
    )

    # ---- Allocation ----
    allocated_hours = fields.Float(
        "Allocated Hours",
        compute="_compute_allocated_hours",
        store=True,
        readonly=False,
        help="Working hours between start and end, respecting the resource calendar.",
    )
    allocated_percentage = fields.Float(
        "Allocation %",
        default=100.0,
        help="Percentage of the resource's work capacity allocated to this schedule.",
    )

    # ---- Conflict detection ----
    schedule_overlap_count = fields.Integer(
        "Scheduling Conflicts",
        compute="_compute_schedule_overlap_count",
    )

    # ---- Origin tracking (generic reference) ----
    res_model = fields.Char(
        "Source Model",
        index=True,
        readonly=True,
        help="Technical name of the model that created this reservation.",
    )
    res_id = fields.Many2oneReference(
        "Source Record",
        model_field="res_model",
        index=True,
        readonly=True,
        help="ID of the record in the source model.",
    )

    # ---- Enforcement ----
    enforcement_mode = fields.Selection(
        [("soft", "Warning"), ("hard", "Block")],
        default="soft",
        required=True,
        help="Soft: overlaps produce a warning. Hard: overlaps raise a validation error.",
    )

    # ---- Display helpers ----
    origin_display = fields.Char(
        "Source",
        compute="_compute_origin_display",
    )
    color = fields.Integer(
        "Color",
        compute="_compute_color",
    )

    # ---- Indexes ----
    _resource_schedule_idx = models.Index("(resource_id, date_start, date_end)")
    _origin_idx = models.Index("(res_model, res_id)")

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------

    @api.constrains("date_start", "date_end")
    def _check_date_sanity(self):
        """Ensure start <= end."""
        for record in self:
            if (
                record.date_start
                and record.date_end
                and record.date_start > record.date_end
            ):
                raise ValidationError(
                    self.env._(
                        "%(name)s: start date must be before end date.",
                        name=record.name,
                    )
                )

    @api.constrains("date_start", "date_end", "resource_id", "allocated_percentage")
    def _check_hard_overlap(self):
        """Block overlapping reservations when enforcement_mode is 'hard'."""
        hard = self.filtered(lambda r: r.enforcement_mode == "hard")
        if not hard:
            return
        # Recompute overlap counts (flushes internally before SQL)
        hard._compute_schedule_overlap_count()
        for record in hard:
            if record.schedule_overlap_count > 0:
                raise ValidationError(
                    self.env._(
                        "%(name)s: %(resource)s is already reserved during this time.",
                        name=record.name,
                        resource=record.resource_id.name,
                    )
                )

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    @api.depends("resource_id", "resource_id.calendar_id")
    def _compute_resource_calendar_id(self):
        """Use the resource's calendar, falling back to the company calendar."""
        for record in self:
            if record.resource_id and record.resource_id.calendar_id:
                record.resource_calendar_id = record.resource_id.calendar_id
            elif record.company_id:
                record.resource_calendar_id = record.company_id.resource_calendar_id
            else:
                record.resource_calendar_id = record.env.company.resource_calendar_id

    @api.depends(
        "date_start",
        "date_end",
        "resource_id",
        "resource_calendar_id",
        "allocated_percentage",
    )
    def _compute_allocated_hours(self):
        """Compute working hours between ``date_start`` and ``date_end``.

        Respects the resource calendar (including flexible resources) and
        applies ``allocated_percentage`` to scale the result.
        """
        for record in self:
            if not record.date_start or not record.date_end:
                record.allocated_hours = 0.0
                continue
            work_hours = record._scheduling_get_work_hours(
                record.date_start,
                record.date_end,
                resource=record.resource_id,
                calendar=record.resource_calendar_id,
            )
            pct = record.allocated_percentage
            record.allocated_hours = round(work_hours * pct / 100.0, 2)

    @api.depends("date_start", "date_end", "resource_id", "allocated_percentage")
    def _compute_schedule_overlap_count(self):
        """SQL-based overlap detection for same-resource schedule conflicts.

        Two records overlap when their datetime ranges intersect AND they
        share the same resource AND their combined allocation exceeds 100%.
        Records without an id (unsaved) or without a resource are skipped.
        """
        stored = self.filtered(
            lambda r: (
                r.id
                and isinstance(r.id, int)
                and r.resource_id
                and r.date_start
                and r.date_end
            )
        )
        (self - stored).schedule_overlap_count = 0
        if not stored:
            return

        stored.flush_recordset(
            ["date_start", "date_end", "resource_id", "allocated_percentage"]
        )
        table = SQL.identifier(self._table)
        query = SQL(
            """
            SELECT s1.id, COUNT(s2.id)
              FROM %s s1
              JOIN %s s2
                ON s1.resource_id = s2.resource_id
               AND s1.id != s2.id
               AND s1.date_start < s2.date_end
               AND s1.date_end > s2.date_start
               AND COALESCE(s1.allocated_percentage, 100)
                 + COALESCE(s2.allocated_percentage, 100) > 100
             WHERE s1.id = ANY(%s)
             GROUP BY s1.id
            """,
            table,
            table,
            list(stored.ids),
        )
        self.env.cr.execute(query)
        counts = dict(self.env.cr.fetchall())
        for record in stored:
            record.schedule_overlap_count = counts.get(record.id, 0)

    @api.depends("res_model", "res_id")
    def _compute_origin_display(self):
        """Resolve the source record's display name."""
        for record in self:
            if record.res_model and record.res_id:
                try:
                    source = self.env[record.res_model].browse(record.res_id)
                    record.origin_display = source.display_name
                except KeyError, ValueError, MissingError:
                    record.origin_display = f"{record.res_model},{record.res_id}"
            else:
                record.origin_display = False

    # Color mapping: different colors per source module for visual distinction
    _COLOR_MAP = {
        "project.task": 1,  # red
        "room.booking": 4,  # blue
        "mrp.workorder": 2,  # orange
    }

    @api.depends("res_model")
    def _compute_color(self):
        """Assign a color index based on the source model for visual distinction."""
        for record in self:
            record.color = self._COLOR_MAP.get(record.res_model, 0)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_open_origin(self):
        """Navigate to the source record."""
        self.ensure_one()
        if not self.res_model or not self.res_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "res_model": self.res_model,
            "res_id": self.res_id,
            "views": [(False, "form")],
            "target": "current",
        }

    # ------------------------------------------------------------------
    # Sync helper for consumer models
    # ------------------------------------------------------------------

    @api.model
    def _sync_reservation(self, record, reservation_vals_list):
        """Reconcile reservations for a consumer record.

        Creates, updates, or deletes reservations so that the given record
        has exactly the reservations described by ``reservation_vals_list``.
        Each dict in the list represents one reservation (e.g. one per
        assignee on a task).  An empty list deletes all reservations.

        :param record: the consumer record (must be saved, not a NewId)
        :param reservation_vals_list: list of dicts with keys:
            ``name``, ``date_start``, ``date_end``, ``resource_id``,
            ``allocated_percentage``, ``enforcement_mode``.
        :return: recordset of current reservations after sync
        """
        if not record.id or not isinstance(record.id, int):
            return self.browse()

        existing = self.sudo().search(
            [
                ("res_model", "=", record._name),
                ("res_id", "=", record.id),
            ]
        )

        if not reservation_vals_list:
            existing.unlink()
            return self.browse()

        # Reconcile by resource_id
        existing_by_resource = {r.resource_id.id: r for r in existing}
        to_create = []
        to_delete = self.browse()

        target_resource_ids = set()
        for vals in reservation_vals_list:
            res_id = vals.get("resource_id") or False
            target_resource_ids.add(res_id)
            base_vals = {
                **vals,
                "res_model": record._name,
                "res_id": record.id,
            }
            if res_id in existing_by_resource:
                existing_by_resource[res_id].write(base_vals)
            else:
                to_create.append(base_vals)

        # Delete reservations for resources no longer needed
        for res_id, reservation in existing_by_resource.items():
            if res_id not in target_resource_ids:
                to_delete |= reservation

        created = self.sudo().create(to_create) if to_create else self.browse()
        if to_delete:
            to_delete.unlink()

        return (existing - to_delete) | created

    # ------------------------------------------------------------------
    # Scheduling query: occupied intervals per resource
    # ------------------------------------------------------------------

    @api.model
    def _reservation_intervals_batch(self, start_dt, end_dt, resources, domain=None):
        """Return occupied intervals per resource from reservation records.

        Produces the same ``{resource_id: Intervals}`` format as
        ``resource.calendar._leave_intervals_batch``, making it a drop-in
        replacement for MRP's slot-finding algorithm.

        :param start_dt: aware datetime, range start
        :param end_dt: aware datetime, range end
        :param resources: ``resource.resource`` recordset
        :param domain: optional extra domain on ``resource.reservation``
        :return: dict mapping ``resource.id`` → :class:`Intervals`
        """
        if not resources:
            return {}

        result = defaultdict(Intervals)
        base_domain = [
            ("resource_id", "in", resources.ids),
            ("date_start", "<", end_dt.astimezone(utc).replace(tzinfo=None)),
            ("date_end", ">", start_dt.astimezone(utc).replace(tzinfo=None)),
            ("active", "=", True),
        ]
        if domain:
            base_domain += domain

        reservations = self.sudo().search(base_domain)
        for res in reservations:
            start = localized(res.date_start)
            end = localized(res.date_end)
            result[res.resource_id.id] |= Intervals([(start, end, res)])

        # Ensure all requested resources have an entry
        for resource in resources:
            if resource.id not in result:
                result[resource.id] = Intervals()

        return dict(result)

    # ------------------------------------------------------------------
    # Utility methods (calendar-aware — duplicated from
    # ``resource.scheduling.mixin`` to keep this model standalone)
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
        """See :meth:`resource.scheduling.mixin._scheduling_get_work_hours`."""
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
        """See :meth:`resource.scheduling.mixin._scheduling_snap_to_calendar`."""
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
        """See :meth:`resource.scheduling.mixin._scheduling_plan_hours`."""
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
        """See :meth:`resource.scheduling.mixin._scheduling_resolve_calendar`."""
        self.ensure_one()
        if resource and resource.calendar_id:
            return resource.calendar_id
        if "resource_calendar_id" in self._fields and self.resource_calendar_id:
            return self.resource_calendar_id
        if "company_id" in self._fields and self.company_id:
            return self.company_id.resource_calendar_id
        return self.env.company.resource_calendar_id
