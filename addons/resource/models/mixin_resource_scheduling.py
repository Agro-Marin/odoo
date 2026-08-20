from odoo import api, fields, models


class MixinResourceScheduling(models.AbstractModel):
    """Projects a consumer's schedule into the shared ``resource.reservation`` ledger.

    This mixin is a *projection*, not a base class.  It owns the mapping from
    consumer state to ledger rows — reconciliation, archive mirroring, orphan
    cleanup — and the read-only query surface over the result.  It owns no
    business field, and deliberately says nothing about what allocation means.

    Provides:
    - Reverse One2many to ``resource.reservation`` via ``(res_model, res_id)``
    - Computed ``schedule_overlap_count``, saved and unsaved records alike
    - CRUD hooks that reconcile reservations via ``_sync_reservations``
    - Contracts consumers override: ``_get_reservation_date_fields``,
      ``_get_reservation_vals_list``, ``_get_sync_trigger_fields``
    - Utility methods (``_scheduling_get_work_hours``,
      ``_scheduling_plan_hours``, ``_scheduling_snap_to_calendar``,
      ``_scheduling_resolve_calendar``) for calendar-aware computations
      independent of field-name conventions

    **Why no allocation fields here.**  Field dependencies *union* along the
    MRO (``odoo/orm/fields/base.py``, ``get_depends``): a consumer that
    overrides a compute inherited from a mixin keeps the mixin's dependency
    edges as well as its own, permanently and invisibly.  A mixin field is
    therefore only safe when no consumer will ever want different semantics.
    ``allocated_hours`` failed that test — task hours are a sum over
    assignees, work-order time is workcenter capacity in minutes, a shift's
    hours invert into a percentage that may exceed 100 — so they live in the
    opt-in :class:`mixin.resource.allocation` instead.
    ``schedule_overlap_count`` passes it: it is derived from the ledger alone.
    """

    _name = "mixin.resource.scheduling"
    _description = "Resource Scheduling Mixin"
    _inherit = ["mixin.resource.scheduling.tools"]

    #: Set to ``True`` by consumers whose ``write`` keeps working after
    #: ``super()`` returns.  The CRUD hooks below then leave the ledger alone
    #: and the consumer calls ``_sync_reservations()`` itself once its own
    #: state is final.
    #:
    #: No hook can infer that moment: ``create``/``write`` are too early for
    #: such a consumer -- projecting from there reads half-settled values and
    #: forces its interdependent computes to resolve in an order they
    #: otherwise would not -- and ``cr.precommit`` is too late to be read, as
    #: it runs only from ``cr.flush()`` (savepoints and commit), not from
    #: ordinary field access.  So the consumer declares it.
    _reservation_sync_manual = False

    # ---- Reservation linkage ----
    reservation_ids = fields.One2many(
        "resource.reservation",
        "res_id",
        string="Reservations",
        domain=lambda self: [("res_model", "=", self._name)],
        bypass_search_access=True,
    )

    # ---- Aggregated conflict count (sums the linked reservations) ----
    schedule_overlap_count = fields.Integer(
        "Scheduling Conflicts",
        compute="_compute_schedule_overlap_count",
        search="_search_schedule_overlap_count",
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
        Consumers add their assignee field on top;
        :class:`mixin.resource.allocation` adds ``allocated_percentage``,
        because the field it declares is one every consumer of it forwards
        into ``_get_reservation_vals_list``.  A trigger left out leaves the
        mirror row stuck at the old value with nothing to indicate it.
        """
        triggers = set()
        start_field, end_field = self._get_reservation_date_fields()
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

        The existing reservations for the whole batch are fetched in one query
        (archived included: they are engine-owned mirror rows, and reconciling
        blind to them would create active duplicates next to archived twins).
        """
        start_field, end_field = self._get_reservation_date_fields()
        if not start_field or not end_field or not self:
            return
        reservation_model = self.env["resource.reservation"]
        existing_all = (
            reservation_model.sudo()
            .with_context(active_test=False)
            .search(
                [
                    ("res_model", "=", self._name),
                    ("res_id", "in", self.ids),
                ]
            )
        )
        existing_by_record = existing_all.grouped("res_id")
        no_reservations = existing_all.browse()  # keeps the sudo/active_test env
        for record in self:
            reservation_model._sync_reservation(
                record,
                record._get_reservation_vals_list(),
                existing=existing_by_record.get(record.id, no_reservations),
            )

    # ------------------------------------------------------------------
    # CRUD hooks (patterned on mixin.rating / mixin.mail.thread)
    # ------------------------------------------------------------------

    def _active_for_sync(self):
        """Records allowed to hold *active* reservations: the active ones.

        An archived consumer must never sync — its reservations are not live
        claims on the resource (see ``write``).  Models without an ``active``
        field are always live.
        """
        if "active" in self._fields:
            return self.filtered("active")
        return self

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self._reservation_sync_manual:
            # Records created already archived (import, copy of an archived
            # record) must not plant active claims on their resources.
            records._active_for_sync()._sync_reservations()
        return records

    def write(self, vals):
        result = super().write(vals)
        start_field, end_field = self._get_reservation_date_fields()
        has_dates = bool(start_field and end_field)

        if "active" in vals and has_dates:
            # Mirror archive state: a record's reservations are no longer claims
            # on the resource once the record is archived, and they come back
            # when it is restored.  Done BEFORE the sync below so a reactivated
            # record's existing (now-active) reservations are found and
            # reconciled instead of being duplicated by fresh creates.
            mirror_active = bool(vals["active"])
            self.env["resource.reservation"].sudo().with_context(
                active_test=False
            ).search(
                [
                    ("res_model", "=", self._name),
                    ("res_id", "in", self.ids),
                    # Only rows actually flipping: a no-op write would still
                    # bump write_date and re-run the overlap constraint sweep.
                    ("active", "!=", mirror_active),
                ]
            ).write({"active": mirror_active})

        # Re-sync when a scheduling field changed, or when the record is being
        # reactivated (its reservations must reflect edits made while archived).
        triggers = self._get_sync_trigger_fields()
        sync_needed = bool(triggers and triggers.intersection(vals.keys()))
        reactivating = bool(vals.get("active")) and has_dates
        if (sync_needed or reactivating) and not self._reservation_sync_manual:
            # Never let an *archived* record sync: doing so would create active
            # reservations — live claims on the resource — for a record that no
            # longer exists to the user.  ``_get_reservation_vals_list`` still
            # returns rows for an archived record, so this guard, not the vals,
            # is what enforces the invariant.
            self._active_for_sync()._sync_reservations()
        return result

    def unlink(self):
        # Capture ids and model name before super(); the recordset is invalid after.
        model_name, record_ids = self._name, self.ids
        result = super().unlink()
        # active_test=False: an archived-then-deleted consumer (the common
        # archive → cleanup flow) has *archived* reservations, which a default
        # search would miss — leaving orphaned rows behind forever.
        self.env["resource.reservation"].sudo().with_context(active_test=False).search(
            [
                ("res_model", "=", model_name),
                ("res_id", "in", record_ids),
            ]
        ).unlink()
        return result

    # ------------------------------------------------------------------
    # Query surface
    # ------------------------------------------------------------------

    def _get_overlap_depends_fields(self):
        """Fields whose change re-evaluates ``schedule_overlap_count``.

        The reservation aggregates answer for saved records.  The sync
        triggers are what an *unsaved* record has instead: it owns no
        reservations, so its count is derived from the very fields that
        ``_get_reservation_vals_list`` reads, and without them here the
        warning would never refresh as the user edits the form.
        """
        return [
            "reservation_ids.schedule_overlap_count",
            "reservation_ids.active",
            *sorted(self._get_sync_trigger_fields()),
        ]

    @api.depends(lambda self: self._get_overlap_depends_fields())
    def _compute_schedule_overlap_count(self):
        """Aggregate overlap counts from linked reservations.

        Unsaved records have no reservations yet, so theirs is swept
        prospectively from the values ``_get_reservation_vals_list`` would
        create.  Without that branch a double-booking stays invisible until
        the record is saved — precisely when the warning stops being useful,
        because the clash has already been committed to the ledger.
        """
        stored = self.filtered(lambda record: isinstance(record.id, int))
        for record in stored:
            record.schedule_overlap_count = sum(
                record.reservation_ids.mapped("schedule_overlap_count")
            )
        for record in self - stored:
            record.schedule_overlap_count = len(record._get_schedule_conflicts())

    def _get_schedule_conflicts(self):
        """Return the reservations this record's schedule collides with.

        Saved records are answered from their own reservations' sweep, unsaved
        ones from a prospective sweep of the bookings they would create.  The
        record's own reservations are never in the result, and both paths run
        the same cumulative sweep, so the answer does not change shape at save
        time — only the ids it is derived from do.

        :return: ``resource.reservation`` recordset
        """
        self.ensure_one()
        return self._get_schedule_conflicts_batch()[self.id]

    def _get_schedule_conflicts_batch(self):
        """Return ``{record id: conflicting reservations}`` for the whole recordset.

        One sweep serves the batch.  Answering per record costs a query each,
        and the callers that matter — a Gantt row set, a list view's conflict
        badge — ask for hundreds at a time.

        Unsaved records still cost a query apiece: they have no stored ledger
        to sweep together, and a form carries one of them, not hundreds.
        """
        reservation_model = self.env["resource.reservation"].sudo()
        empty = reservation_model.browse()
        result = dict.fromkeys(self._ids, empty)

        stored = self.filtered(lambda record: isinstance(record.id, int))
        own_by_record = {record.id: record.reservation_ids.sudo() for record in stored}
        all_own = empty
        for own in own_by_record.values():
            all_own |= own
        if all_own:
            partners = all_own._conflicting_reservations()
            for record_id, own in own_by_record.items():
                found = empty
                for reservation in own:
                    found |= partners.get(reservation.id, empty)
                # A multi-resource consumer books several reservations; two of
                # its own colliding with each other is not a conflict with
                # anything else, and reporting it would leave every such record
                # permanently self-conflicted.
                result[record_id] = found - own

        for record in self - stored:
            # A form editing a *saved* record hands the compute a virtual
            # record carrying an ``_origin``. Its stored bookings are the very
            # ones this edit would replace, so counting them would report every
            # edited record as conflicting with itself.  ``_origin`` is an empty
            # recordset for a genuinely new record, yielding no ids to ignore.
            result[record.id] = reservation_model._prospective_conflicts(
                record._get_reservation_vals_list(),
                ignore_ids=record._origin.reservation_ids.ids,
            )
        return result

    @api.model
    def _search_schedule_overlap_count(self, operator, value):
        """Let consumers filter their own conflicted records.

        Only ``in conflict`` / ``not in conflict`` is expressible here: this
        field is a *sum* over the record's reservations, and the reservation
        model can only answer per-row questions, so a threshold on the sum
        cannot be pushed down. Zero-vs-nonzero is the question views and crons
        actually ask, and it maps exactly: a record has a nonzero sum iff at
        least one of its reservations is conflicted (counts are never negative).
        """
        if not isinstance(value, int) or value != 0 or operator not in ("=", "!="):
            return NotImplemented
        conflicted = (
            self.env["resource.reservation"]
            .sudo()
            .search(
                [("res_model", "=", self._name), ("schedule_overlap_count", ">", 0)]
            )
        )
        record_ids = list({reservation.res_id for reservation in conflicted})
        return [("id", "not in" if operator == "=" else "in", record_ids)]
