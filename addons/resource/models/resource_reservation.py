from collections import defaultdict

from pytz import utc

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.libs.intervals import Intervals
from odoo.tools import SQL
from odoo.tools.date_utils import localized


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
    _inherit = ["resource.scheduling.tools"]
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
        Only ``active`` reservations are considered on both sides: an archived
        reservation is no longer a claim on the resource.  Records without an
        id (unsaved) or without a resource are skipped.

        Known limitation: the check is *pairwise* — it flags a record only if
        it exceeds 100% against some single other reservation.  A cumulative
        over-allocation spread over three or more partial reservations (e.g.
        3 × 50 % = 150 %) where no individual pair exceeds 100 % is NOT
        detected.  Fixing that requires a windowed/sweep-line sum of
        allocations per resource; deferred as it changes the meaning of the
        displayed conflict count.
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

        # The self-join below reads sibling rows (s2) straight from the table,
        # so every pending change to those columns — not just on ``stored`` —
        # must be flushed first, otherwise an unflushed archive/allocation edit
        # on another reservation would be invisible to the overlap query.
        self.flush_model(
            ["date_start", "date_end", "resource_id", "allocated_percentage", "active"]
        )
        table = SQL.identifier(self._table)
        query = SQL(
            """
            SELECT s1.id, COUNT(s2.id)
              FROM %s s1
              JOIN %s s2
                ON s1.resource_id = s2.resource_id
               AND s1.id != s2.id
               AND s2.active
               AND s1.date_start < s2.date_end
               AND s1.date_end > s2.date_start
               AND COALESCE(s1.allocated_percentage, 100)
                 + COALESCE(s2.allocated_percentage, 100) > 100
             WHERE s1.id = ANY(%s)
               AND s1.active
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
        """Resolve each source record's display name (batched per model)."""
        self.origin_display = False
        with_origin = self.filtered(lambda r: r.res_model and r.res_id)
        for model_name, records in with_origin.grouped("res_model").items():
            if model_name not in self.env:
                # Model belongs to an uninstalled module: fall back to the raw ref.
                for record in records:
                    record.origin_display = f"{model_name},{record.res_id}"
                continue
            # One browse for the whole group; ``exists()`` drops stale ids in a
            # single query so a deleted source falls back to the raw reference
            # instead of raising ``MissingError`` (the old per-record behaviour).
            sources = self.env[model_name].browse(records.mapped("res_id")).exists()
            names = dict(zip(sources.ids, sources.mapped("display_name"), strict=True))
            for record in records:
                record.origin_display = names.get(record.res_id) or (
                    f"{model_name},{record.res_id}"
                )

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
