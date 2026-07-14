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

    @api.constrains(
        "date_start",
        "date_end",
        "resource_id",
        "allocated_percentage",
        "active",
        "enforcement_mode",
    )
    def _check_hard_overlap(self):
        """Block overlapping reservations when enforcement_mode is 'hard'.

        ``active`` and ``enforcement_mode`` are triggers too: unarchiving a
        reservation re-asserts its claim on the resource, and switching to
        ``hard`` opts in to blocking — both must re-validate.
        """
        hard = self.filtered(lambda r: r.active and r.enforcement_mode == "hard")
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

    @api.depends("resource_id", "resource_id.calendar_id", "company_id")
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
        """Sweep-line overlap detection for same-resource schedule conflicts.

        A reservation is in conflict when, at some instant within its window,
        the *cumulative* allocation of all active reservations on the same
        resource covering that instant exceeds 100%.  ``schedule_overlap_count``
        is the number of distinct other reservations that share at least one
        such over-allocated instant with it.

        This is strictly more correct than a pairwise check: a cumulative
        over-allocation spread over three or more partial reservations (e.g.
        3 × 50% = 150%) where no individual *pair* exceeds 100% is detected,
        while the pairwise cases (2 × 100%, adjacent, different resource) keep
        their previous counts.

        Only ``active`` reservations count on both sides — an archived
        reservation is no longer a claim on the resource.  Records without a
        stored id, a resource, or a date range are skipped (count 0).
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

        # The query below reads sibling rows straight from the table, so every
        # pending change to those columns — not just on ``stored`` — must be
        # flushed first, otherwise an unflushed archive/allocation edit on
        # another reservation would be invisible to the sweep.
        self.flush_model(
            ["date_start", "date_end", "resource_id", "allocated_percentage", "active"]
        )
        # Fetch every active, dated reservation for the involved resources in a
        # single query, then sweep each resource's timeline in Python (the row
        # count per resource is small in practice).
        self.env.cr.execute(
            SQL(
                """
                SELECT id, resource_id, date_start, date_end,
                       COALESCE(allocated_percentage, 100)
                  FROM %s
                 WHERE resource_id = ANY(%s)
                   AND active
                   AND date_start IS NOT NULL
                   AND date_end IS NOT NULL
                """,
                SQL.identifier(self._table),
                list(set(stored.resource_id.ids)),
            )
        )
        rows_by_resource = defaultdict(list)
        for res_id, resource_id, date_start, date_end, pct in self.env.cr.fetchall():
            rows_by_resource[resource_id].append((res_id, date_start, date_end, pct))

        conflict_partners = self._sweep_overlap_partners(rows_by_resource)
        for record in stored:
            record.schedule_overlap_count = len(conflict_partners.get(record.id, ()))

    @staticmethod
    def _sweep_overlap_partners(rows_by_resource):
        """Return ``{reservation_id: set(conflicting reservation ids)}``.

        The cumulative allocation on a resource is a step function that only
        changes at reservation boundaries and can only *rise* at a start.  So
        every maximal over-100% region begins exactly at some start boundary;
        evaluating the covering set at each start instant is therefore
        sufficient to find all conflicts.
        """
        partners = defaultdict(set)
        for rows in rows_by_resource.values():
            starts = sorted({row[1] for row in rows})
            for instant in starts:
                covering = [
                    (res_id, pct)
                    for res_id, date_start, date_end, pct in rows
                    if date_start <= instant < date_end
                ]
                if sum(pct for _res_id, pct in covering) <= 100:
                    continue
                ids_here = [res_id for res_id, _pct in covering]
                for res_id in ids_here:
                    partners[res_id].update(
                        other for other in ids_here if other != res_id
                    )
        return partners

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
    def _sync_reservation(self, record, reservation_vals_list, existing=None):
        """Reconcile reservations for a consumer record.

        Creates, updates, or deletes reservations so that the given record
        has exactly the reservations described by ``reservation_vals_list``.
        Each dict in the list represents one reservation (e.g. one per
        assignee on a task).  An empty list deletes all reservations.

        Reservations here are engine-owned mirror rows: the reconciliation
        covers *archived* ones too (else an archived twin would sit next to a
        freshly created active duplicate and both would come alive on the next
        consumer unarchive), and any row it keeps is forced back to active —
        the caller only ever syncs active consumers.

        :param record: the consumer record (must be saved, not a NewId)
        :param reservation_vals_list: list of dicts with keys:
            ``name``, ``date_start``, ``date_end``, ``resource_id``,
            ``allocated_percentage``, ``enforcement_mode``.
        :param existing: optional pre-fetched reservations of ``record``
            (must include archived ones); avoids one query per record when
            the caller batches (see ``_sync_reservations``).
        :return: recordset of current reservations after sync
        """
        if not record.id or not isinstance(record.id, int):
            return self.browse()

        if existing is None:
            existing = (
                self.sudo()
                .with_context(active_test=False)
                .search(
                    [
                        ("res_model", "=", record._name),
                        ("res_id", "=", record.id),
                    ]
                )
            )

        if not reservation_vals_list:
            existing.unlink()
            return self.browse()

        # Reconcile by resource_id.  Keep a *list* per resource: a consumer may
        # legitimately hold several reservations sharing one resource (or
        # several with no resource, all keyed ``False``).  Keying by a single
        # record would hide the duplicates — they would be neither updated nor
        # deleted and would linger as phantom conflicts on the resource.
        existing_by_resource = defaultdict(list)
        for reservation in existing:
            existing_by_resource[reservation.resource_id.id].append(reservation)
        to_create = []

        for vals in reservation_vals_list:
            res_id = vals.get("resource_id") or False
            base_vals = {
                **vals,
                "res_model": record._name,
                "res_id": record.id,
                "active": True,
            }
            bucket = existing_by_resource.get(res_id)
            if bucket:
                # Reuse one existing reservation per requested val, writing
                # only what actually changed: consumers re-sync on every edit
                # of a trigger field, and a no-op write would still re-run the
                # overlap sweep and bump write_date on each of them.
                reservation = bucket.pop(0)
                changed_vals = {
                    fname: value
                    for fname, value in base_vals.items()
                    if reservation._fields[fname].convert_to_write(
                        reservation[fname], reservation
                    )
                    != value
                }
                if changed_vals:
                    reservation.write(changed_vals)
            else:
                to_create.append(base_vals)

        # Whatever is left unclaimed in any bucket is surplus: the resource is
        # no longer wanted, or it was a duplicate now needing fewer records.
        to_delete = self.browse().union(
            *(
                reservation
                for bucket in existing_by_resource.values()
                for reservation in bucket
            )
        )

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

        base_domain = [
            ("resource_id", "in", resources.ids),
            ("date_start", "<", end_dt.astimezone(utc).replace(tzinfo=None)),
            ("date_end", ">", start_dt.astimezone(utc).replace(tzinfo=None)),
            ("active", "=", True),
        ]
        if domain:
            base_domain += domain

        # Collect the raw tuples per resource first, then build each Intervals
        # once.  Merging with ``|=`` inside the loop re-sorts and re-merges the
        # whole set on every reservation (O(n²) for a busy resource).
        tuples_by_resource = defaultdict(list)
        for res in self.sudo().search(base_domain):
            tuples_by_resource[res.resource_id.id].append(
                (localized(res.date_start), localized(res.date_end), res)
            )

        # Ensure all requested resources have an entry (empty if unbooked).
        return {
            resource.id: Intervals(tuples_by_resource.get(resource.id, []))
            for resource in resources
        }
