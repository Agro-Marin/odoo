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
        start_field, end_field = self._get_reservation_date_fields()
        if "active" in vals and start_field and end_field:
            # Mirror archive state: a record's reservations are no longer
            # claims on the resource once the record is archived, and they come
            # back when it is restored.  Skipped for consumers that never
            # create reservations (no scheduling date fields).
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

    @api.depends("reservation_ids.allocated_hours")
    def _compute_allocated_hours(self):
        """Aggregate committed hours from the consumer's reservation ledger."""
        for record in self:
            record.allocated_hours = sum(
                record.reservation_ids.mapped("allocated_hours")
            )

    @api.depends("reservation_ids.schedule_overlap_count")
    def _compute_schedule_overlap_count(self):
        """Aggregate overlap counts from linked reservations."""
        for record in self:
            record.schedule_overlap_count = sum(
                record.reservation_ids.mapped("schedule_overlap_count")
            )
