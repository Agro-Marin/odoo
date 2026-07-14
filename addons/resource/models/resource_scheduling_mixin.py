from odoo import api, fields, models


class ResourceSchedulingMixin(models.AbstractModel):
    """Consumer-facing mixin for models that delegate scheduling data to resource.reservation.

    Provides:
    - Reverse One2many to ``resource.reservation`` via ``(res_model, res_id)``
    - Shared ``allocated_percentage`` (input passed through to reservations)
    - Computed ``allocated_hours`` aggregated from ``reservation_ids``
      (PMI Work semantic: sum of person-hours committed across resources)
    - Computed ``schedule_overlap_count`` aggregated from reservations
    - CRUD hooks that reconcile reservations via ``_sync_reservations``
    - Contracts consumers override: ``_get_reservation_date_fields``,
      ``_get_reservation_vals_list``, ``_get_sync_trigger_fields``
    - Utility methods (``_scheduling_get_work_hours``,
      ``_scheduling_plan_hours``, ``_scheduling_snap_to_calendar``,
      ``_scheduling_resolve_calendar``) for calendar-aware computations
      independent of field-name conventions

    Consumers that need a planning estimate independent of resource
    commitment (e.g. ``project.task.planned_hours``) declare it locally;
    the mixin only computes the *committed* side.  See PMI hours model in
    ``knowledge/agromarin-knowledge/reference/business/pmi-hours-model.md``.
    """

    _name = "resource.scheduling.mixin"
    _description = "Resource Scheduling Mixin"
    _inherit = ["resource.scheduling.tools"]

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
    # CRUD hooks (patterned on rating.mixin / mail.thread)
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
        if sync_needed or reactivating:
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
    # Generic computes
    # ------------------------------------------------------------------

    # ``reservation_ids.active`` is a dependency on purpose: ``reservation_ids``
    # drops archived rows on read (x2many active_test), so an archive flip
    # changes both aggregates without touching the relation or the summed
    # fields themselves — without it the stored sums go stale.
    @api.depends("reservation_ids.allocated_hours", "reservation_ids.active")
    def _compute_allocated_hours(self):
        """Aggregate committed hours from the consumer's reservation ledger."""
        for record in self:
            record.allocated_hours = sum(
                record.reservation_ids.mapped("allocated_hours")
            )

    @api.depends("reservation_ids.schedule_overlap_count", "reservation_ids.active")
    def _compute_schedule_overlap_count(self):
        """Aggregate overlap counts from linked reservations."""
        for record in self:
            record.schedule_overlap_count = sum(
                record.reservation_ids.mapped("schedule_overlap_count")
            )
