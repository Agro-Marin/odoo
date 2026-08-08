import logging
import operator as operator_module
from collections import defaultdict

from pytz import utc

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.libs.intervals import Intervals
from odoo.tools import SQL
from odoo.tools.date_utils import localized, sum_intervals

_logger = logging.getLogger(__name__)

# Scalar comparisons the conflict search accepts.  A fixed map, so no operator
# string from a domain ever reaches Python's ``eval`` path or the query.
COMPARATORS = {
    "=": operator_module.eq,
    "!=": operator_module.ne,
    "<": operator_module.lt,
    "<=": operator_module.le,
    ">": operator_module.gt,
    ">=": operator_module.ge,
}


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
    # ``check_company=True`` on a field is inert on its own — the ORM only runs
    # ``_check_company`` from create/write when the model opts in here.
    _check_company_auto = True

    # ---- Identity ----
    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    # No ``default=``: a default counts as an explicit value and would beat the
    # precompute, which is exactly how bookings ended up stamped with the
    # acting user's company instead of the resource's.
    company_id = fields.Many2one(
        "res.company",
        compute="_compute_company_id",
        store=True,
        readonly=False,
        precompute=True,
        index="btree_not_null",
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
        check_company=True,
        help="The resource (person, equipment) assigned to this schedule.",
    )
    resource_calendar_id = fields.Many2one(
        "resource.calendar",
        "Working Calendar",
        compute="_compute_resource_calendar_id",
        store=True,
        readonly=False,
        check_company=True,
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
    # A share of capacity outside 0..100 is not a booking, it is a data error —
    # and a *negative* one is an integrity hole: the cumulative sweep below adds
    # these values up, so a -100% row cancels a real 100% booking, drops
    # ``schedule_overlap_count`` to zero and lets a reservation slip past
    # ``enforcement_mode = 'hard'`` entirely.  The sweep query in
    # ``_compute_schedule_overlap_count`` clamps the column as well, so rows
    # predating this constraint cannot disarm the check either.
    #
    # A table constraint rather than ``@api.constrains``: it fires before any
    # Python constraint would (making one here dead code), its message is what
    # the web client shows, and it is the only form that also covers rows
    # written by raw SQL.  Consumers get the friendlier field-level error from
    # ``resource.scheduling.mixin``, which has no table of its own.
    _check_allocated_percentage = models.Constraint(
        "CHECK(allocated_percentage >= 0 AND allocated_percentage <= 100)",
        "Allocation % must be between 0 and 100.",
    )

    # ---- Conflict detection ----
    schedule_overlap_count = fields.Integer(
        "Scheduling Conflicts",
        compute="_compute_schedule_overlap_count",
        search="_search_schedule_overlap_count",
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

        Validation is not limited to the records being written.  A ``hard``
        reservation is a claim *against everyone*, so a record moving into its
        window must be refused even when that record is itself ``soft`` — and
        ``soft`` is the default every consumer creates.  Checking only ``self``
        meant a "Block" slot was trivially overrun by creating or rescheduling
        the conflicting booking second; only the mirror case (the hard record
        moving) was caught.
        """
        live = self.filtered(
            lambda r: r.active and r.resource_id and r.date_start and r.date_end
        )
        hard = live.filtered(lambda r: r.enforcement_mode == "hard")

        # Hard reservations, not in this batch, whose slot these records intrude on.
        if live:
            hard |= (
                self.sudo()
                .search(
                    [
                        ("id", "not in", live.ids),
                        ("active", "=", True),
                        ("enforcement_mode", "=", "hard"),
                        ("resource_id", "in", live.resource_id.ids),
                        ("date_start", "<", max(live.mapped("date_end"))),
                        ("date_end", ">", min(live.mapped("date_start"))),
                    ]
                )
                .with_env(self.env)
            )
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

    @api.depends("resource_id.company_id")
    def _compute_company_id(self):
        """Inherit the booked resource's company.

        A reservation is a claim on a *resource*, so it belongs to that
        resource's company.  Defaulting to ``env.company`` instead let a user
        acting in company B book a company-A resource; the multi-company rule
        then hid that booking from company A, whose users saw the resource as
        free while it was in fact taken.  ``check_company`` on ``resource_id``
        now rejects the mismatch outright, and this keeps the common path from
        ever hitting it.
        """
        for record in self:
            record.company_id = (
                record.resource_id.company_id or record.company_id or self.env.company
            )

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

        Records sharing a resource *and* calendar are resolved together: the
        work intervals are fetched once for the group's union window and each
        record is then measured against that cached set.  Computing per record
        cost ~2 extra queries each (167 queries for 80 reservations, against 5
        when the value is supplied), which is pure overhead whenever a
        consumer syncs a batch of reservations.

        Flexible resources keep the per-record path: their synthesized
        intervals depend on the queried window, so a group-wide window would
        not give the same answer as the individual ones.

        ``resource_calendar_id`` is authoritative whenever it was set to
        something other than what the resource itself resolves to.  It used to
        be honoured only for reservations *without* a resource: with one,
        ``_get_valid_work_intervals`` re-derived the calendar from
        ``resource.calendar_id`` and the stored override was silently dropped,
        so one stored, user-writable, ``@api.depends``-declared field had two
        different meanings depending on a neighbouring field.  Records that did
        not override it still go through ``_get_valid_work_intervals``, which is
        the hook ``hr`` overrides to switch calendars mid-window by contract.
        """
        undated = self.filtered(lambda r: not r.date_start or not r.date_end)
        undated.allocated_hours = 0.0
        dated = self - undated
        if not dated:
            return

        flexible = dated.filtered(
            lambda r: r.resource_id and r.resource_id._is_flexible()
        )
        for record in flexible:
            record.allocated_hours = record._scale_allocation(
                record._scheduling_get_work_hours(
                    record.date_start,
                    record.date_end,
                    resource=record.resource_id,
                    calendar=record.resource_calendar_id,
                )
            )

        # Group by *calendar*, not by (calendar, resource): the underlying
        # ``_get_valid_work_intervals`` already resolves many resources in one
        # go, so one group per calendar collapses the whole batch into a
        # handful of queries.  Grouping per resource would leave one round trip
        # per record, which is the very cost this avoids.
        groups = defaultdict(self.browse)
        for record in dated - flexible:
            groups[record.resource_calendar_id] |= record

        attendance = self.env["resource.calendar.attendance"]
        for calendar, records in groups.items():
            window_start = localized(min(records.mapped("date_start")))
            window_end = localized(max(records.mapped("date_end")))

            # Resources whose own calendar already *is* this group's calendar
            # go through the contract-aware resolver; the rest asked explicitly
            # for this calendar, so it is applied directly to them.  An unset
            # ``resource_calendar_id`` is not an override — it states nothing,
            # so those resources keep resolving their own calendar as before.
            if calendar:
                # ``calendar=calendar`` binds the loop variable at definition time.
                # The lambda is consumed inside this iteration so the late-binding
                # bug never fired, but ruff's B023 flags it and the guard costs
                # nothing.
                native = records.resource_id.filtered(
                    lambda resource, calendar=calendar: resource.calendar_id == calendar
                )
            else:
                native = records.resource_id
            overridden = records.resource_id - native
            intervals_per_resource = {}
            if native:
                intervals_per_resource, _calendar_intervals = (
                    native._get_valid_work_intervals(window_start, window_end)
                )
            if overridden and calendar:
                intervals_per_resource.update(
                    calendar._work_intervals_batch(
                        window_start, window_end, resources=overridden
                    )
                )
            calendar_intervals = None
            if len(records.filtered(lambda r: not r.resource_id)) and calendar:
                calendar_intervals = calendar._work_intervals_batch(
                    window_start, window_end
                )[False]

            for record in records:
                if record.resource_id:
                    intervals = intervals_per_resource.get(record.resource_id.id)
                elif calendar_intervals is not None:
                    intervals = calendar_intervals
                else:
                    # No resource and no calendar: fall back to raw elapsed time.
                    span = localized(record.date_end) - localized(record.date_start)
                    record.allocated_hours = record._scale_allocation(
                        span.total_seconds() / 3600.0
                    )
                    continue
                clipped = (intervals or Intervals()) & Intervals(
                    [
                        (
                            localized(record.date_start),
                            localized(record.date_end),
                            attendance,
                        )
                    ]
                )
                record.allocated_hours = record._scale_allocation(
                    sum_intervals(clipped)
                )

    def _scale_allocation(self, work_hours):
        """Apply ``allocated_percentage`` to a raw working-hours figure."""
        self.ensure_one()
        return round(work_hours * self.allocated_percentage / 100.0, 2)

    @api.depends(
        "date_start", "date_end", "resource_id", "allocated_percentage", "active"
    )
    def _compute_schedule_overlap_count(self):
        """Sweep-line overlap detection for same-resource schedule conflicts.

        .. note::
           The value depends on *sibling rows*, which ``@api.depends`` cannot
           express: archiving or moving another reservation does not
           invalidate this one's cached count within the same transaction.
           A fresh read (the normal request path) is always correct, and
           ``_check_hard_overlap`` recomputes explicitly rather than trusting
           the cache.  ``active`` is listed so at least the record's own
           archive flip invalidates it.

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
        # Fetch the potentially-conflicting rows in a single query, then sweep
        # each resource's timeline in Python.
        #
        # The window bound matters: without it the query returned every
        # reservation the resource ever had, so computing the count for one
        # 2025 booking pulled in bookings from years earlier and the cost grew
        # with the resource's whole history instead of with the period under
        # test.  Only rows intersecting the union window of ``stored`` can
        # possibly overlap one of them.
        window_start = min(stored.mapped("date_start"))
        window_end = max(stored.mapped("date_end"))
        rows_by_resource = self._overlap_rows(
            (
                SQL("AND resource_id = ANY(%s)", list(set(stored.resource_id.ids))),
                SQL("AND date_start < %s", window_end),
                SQL("AND date_end > %s", window_start),
            )
        )

        conflict_partners = self._sweep_overlap_partners(rows_by_resource)
        for record in stored:
            record.schedule_overlap_count = len(conflict_partners.get(record.id, ()))

    def _overlap_rows(self, extra_conditions=()):
        """Fetch the candidate rows for the sweep, grouped per resource.

        Shared by the compute (which bounds the fetch to the window under test)
        and the search (which cannot). Returns ``{resource_id: [(id, start, end,
        pct)]}`` with the allocation clamped to 0..100, so rows predating the
        table constraint cannot disarm the check.
        """
        self.env.cr.execute(
            SQL(
                """
                SELECT id, resource_id, date_start, date_end,
                       LEAST(100, GREATEST(0, COALESCE(allocated_percentage, 100)))
                  FROM %s
                 WHERE resource_id IS NOT NULL
                   AND active
                   AND date_start IS NOT NULL
                   AND date_end IS NOT NULL
                   %s
                """,
                SQL.identifier(self._table),
                SQL(" ").join(extra_conditions),
            )
        )
        rows_by_resource = defaultdict(list)
        for res_id, resource_id, date_start, date_end, pct in self.env.cr.fetchall():
            rows_by_resource[resource_id].append((res_id, date_start, date_end, pct))
        return rows_by_resource

    @api.model
    def _search_schedule_overlap_count(self, operator, value):
        """Make the conflict ledger queryable.

        Without this the field was compute-only, so the cross-module
        double-booking detection this model exists for (see the class docstring)
        could not be expressed as a domain at all: no search-view filter, no
        cron, no report -- a conflict was visible only by opening the one record
        that reported it. ``search([("schedule_overlap_count", ">", 0)])`` raised
        ``Cannot convert ... to SQL because it is not stored``.

        The sweep is the same pure function the compute uses, so the two can
        never disagree about what a conflict is.
        """
        if operator not in COMPARATORS or not isinstance(value, int):
            return NotImplemented
        compare = COMPARATORS[operator]

        # Same reason as in the compute: the sweep reads sibling rows straight
        # from the table, so pending writes must reach it first.
        self.flush_model(
            ["date_start", "date_end", "resource_id", "allocated_percentage", "active"]
        )
        partners = self._sweep_overlap_partners(self._overlap_rows())
        conflicted = {res_id: len(peers) for res_id, peers in partners.items()}

        if compare(0, value):
            # Zero matches, so the answer is "everything except the conflicted
            # rows that do not match" -- which also correctly sweeps in archived,
            # resource-less and undated rows, none of which the query above
            # returns and all of which have a count of 0.
            excluded = [
                res_id
                for res_id, count in conflicted.items()
                if not compare(count, value)
            ]
            return [("id", "not in", excluded)]
        return [
            (
                "id",
                "in",
                [
                    res_id
                    for res_id, count in conflicted.items()
                    if compare(count, value)
                ],
            )
        ]

    @staticmethod
    def _sweep_overlap_partners(rows_by_resource):
        """Return ``{reservation_id: set(conflicting reservation ids)}``.

        The cumulative allocation on a resource is a step function that only
        changes at reservation boundaries and can only *rise* at a start.  So
        every maximal over-100% region begins exactly at some start boundary;
        evaluating the covering set at each start instant is therefore
        sufficient to find all conflicts.

        This walks the boundaries once (O(n log n) for the sort, then O(1)
        amortised bookkeeping per event) instead of rescanning every row at
        every distinct start, which was quadratic *regardless* of whether any
        conflict existed — 2 000 bookings on one resource cost ~140 ms of pure
        rescanning.  Now the only super-linear term is the conflict output
        itself, which is empty in the healthy case.

        Intervals are half-open: a booking ending exactly when another starts
        does not overlap it, so ``close`` events are applied before ``open``
        events at the same instant.
        """
        partners = defaultdict(set)
        for rows in rows_by_resource.values():
            events = []
            for res_id, date_start, date_end, pct in rows:
                if date_end <= date_start:
                    # Zero-length bookings cover no instant.
                    continue
                events.append((date_start, 1, res_id, pct))
                events.append((date_end, 0, res_id, pct))
            # (instant, kind) with kind 0 = close sorts before kind 1 = open.
            events.sort(key=lambda event: (event[0], event[1]))

            active = {}
            for _instant, kind, res_id, pct in events:
                if not kind:
                    active.pop(res_id, None)
                    continue
                active[res_id] = pct
                # Re-sum rather than keeping a running total: the values are
                # floats and a running total would accumulate drift across
                # thousands of events, eventually mis-classifying an exact
                # 50 + 50 = 100 as a conflict.
                if sum(active.values()) <= 100:
                    continue
                ids_here = list(active)
                for other_id in ids_here:
                    partners[other_id].update(
                        peer for peer in ids_here if peer != other_id
                    )
        return partners

    @api.depends("res_model", "res_id")
    def _compute_origin_display(self):
        """Resolve each source record's display name (batched per model).

        The name is only disclosed to a reader who may read the source record.
        Reservations are visible to every internal user (they are the shared
        booking ledger), so resolving the name unconditionally published the
        title of records the reader has no access to — a user without project
        rights could read every scheduled task's name straight off the
        reservation list.  Unreadable sources fall back to the same raw
        ``model,id`` reference already used for deleted ones and for models
        whose module is uninstalled.
        """
        self.origin_display = False
        with_origin = self.filtered(lambda r: r.res_model and r.res_id)
        for model_name, records in with_origin.grouped("res_model").items():
            if model_name not in self.env:
                # Model belongs to an uninstalled module: fall back to the raw ref.
                for record in records:
                    record.origin_display = f"{model_name},{record.res_id}"
                continue
            # One browse for the whole group; ``_filtered_access`` drops both
            # stale ids and forbidden ones in a single pass, so neither a
            # deleted source (``MissingError``) nor an unreadable one
            # (``AccessError``) can surface from reading a reservation.
            sources = (
                self.env[model_name]
                .browse(records.mapped("res_id"))
                .exists()
                ._filtered_access("read")
            )
            names = dict(zip(sources.ids, sources.mapped("display_name"), strict=True))
            for record in records:
                record.origin_display = names.get(record.res_id) or (
                    f"{model_name},{record.res_id}"
                )

    # A ``color`` field computed from a hard-coded {res_model: index} map used
    # to live here.  Nothing read it — the calendar view colours by
    # ``resource_id``, no other view, asset or module referenced it — and the
    # map only knew three consumer models, so every other one silently got 0.
    # Removed rather than wired up: which consumer a booking came from is
    # already carried by ``origin_display``, and colouring the shared ledger by
    # *resource* is what makes a double-booking visible.

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    @api.autovacuum
    def _gc_orphan_reservations(self):
        """Drop reservations whose source record is gone.

        ``res_id`` is a ``Many2oneReference``, so there is no foreign key to
        cascade.  ``resource.scheduling.mixin.unlink`` cleans up on the normal
        path, but anything that routes around it -- raw SQL, a consumer that
        overrides ``unlink`` without calling super, a model that leaves the
        registry -- strands rows here.  They are not inert: an orphan is still
        ``active``, still holds a ``resource_id``, and still counts in the
        overlap sweep, so it inflates conflict counts and can block a legitimate
        booking under ``enforcement_mode = 'hard'`` on behalf of a record that
        no longer exists.
        """
        reservations = self.sudo().with_context(active_test=False)
        # One anti-join per distinct source model, rather than loading the whole
        # ledger into memory to filter it in Python.  A healthy installation
        # returns nothing from every query, so the nightly pass costs one cheap
        # indexed scan per consumer model.
        model_names = [
            res_model
            for [res_model] in reservations._read_group(
                [("res_model", "!=", False)], groupby=["res_model"]
            )
        ]
        orphan_ids = []
        for model_name in model_names:
            model = self.env.get(model_name)
            if model is None or not model._auto:
                # The owning module is uninstalled, or the source is an abstract
                # or transient model with no table to point at.  Either way the
                # rows can never be resolved again.
                orphan_ids.extend(
                    reservations.search([("res_model", "=", model_name)]).ids
                )
                continue
            self.env.cr.execute(
                SQL(
                    """
                    SELECT reservation.id
                      FROM %s AS reservation
                 LEFT JOIN %s AS source ON source.id = reservation.res_id
                     WHERE reservation.res_model = %s
                       AND source.id IS NULL
                    """,
                    SQL.identifier(self._table),
                    SQL.identifier(model._table),
                    model_name,
                )
            )
            orphan_ids.extend(row[0] for row in self.env.cr.fetchall())

        if orphan_ids:
            _logger.info(
                "Garbage-collecting %s orphan resource.reservation record(s)",
                len(orphan_ids),
            )
            reservations.browse(orphan_ids).unlink()

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

        # Release the surplus *before* creating replacements: a surplus row is
        # still an active claim on its resource until it is gone, so creating
        # first lets it collide with its own replacement under
        # ``enforcement_mode = 'hard'`` and abort a sync that is only shuffling
        # rows around.
        if to_delete:
            to_delete.unlink()
        created = self.sudo().create(to_create) if to_create else self.browse()

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
