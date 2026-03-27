from collections import defaultdict

from pytz import utc

from odoo import api, fields, models
from odoo.exceptions import MissingError, ValidationError
from odoo.libs.intervals import Intervals
from odoo.tools.date_utils import localized


class ResourceReservation(models.Model):
    """Concrete booking record for any resource over a time window.

    Inherits :class:`resource.scheduling.mixin` for date/time range,
    resource/calendar assignment, allocated hours/percentage, and overlap
    detection.  Adds origin tracking (generic reference via ``res_model`` /
    ``res_id``) and enforcement mode (soft warning vs hard block).

    Consumer models (project.task, room.booking, mrp.workorder, ...) create
    reservations via :meth:`_sync_reservation` and clean up via
    ``@api.ondelete``.  All reservations live in one table, enabling
    cross-module conflict detection (e.g. a person double-booked across
    a task and a room).
    """

    _name = "resource.reservation"
    _description = "Resource Reservation"
    _inherit = ["resource.scheduling.mixin"]
    _order = "date_start"

    # ---- Identity ----
    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
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

    # ---- Composite index for origin lookups ----
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
