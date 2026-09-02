import logging
import operator as operator_module
from collections import defaultdict
from datetime import UTC

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.libs.intervals import Intervals
from odoo.tools import SQL
from odoo.tools.date_utils import localized, sum_intervals

_logger = logging.getLogger(__name__)

COMPARATORS = {
    "=": operator_module.eq,
    "!=": operator_module.ne,
    "<": operator_module.lt,
    "<=": operator_module.le,
    ">": operator_module.gt,
    ">=": operator_module.ge,
}


class ResourceReservation(models.Model):
    _name = "resource.reservation"
    _description = "Resource Reservation"
    _inherit = ["mixin.resource.scheduling.tools"]
    _order = "date_start"
    _check_company_auto = True

    _OVERLAP_SWEEP_FIELDS = [
        "date_start",
        "date_end",
        "resource_id",
        "allocated_percentage",
        "active",
    ]

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        compute="_compute_company_id",
        store=True,
        readonly=False,
        precompute=True,
        index="btree_not_null",
    )

    date_start = fields.Datetime(
        "Scheduled Start",
        index=True,
    )
    date_end = fields.Datetime(
        "Scheduled End",
        index=True,
    )

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
    _check_allocated_percentage = models.Constraint(
        "CHECK(allocated_percentage >= 0 AND allocated_percentage <= 100)",
        "Allocation % must be between 0 and 100.",
    )

    schedule_overlap_count = fields.Integer(
        "Scheduling Conflicts",
        compute="_compute_schedule_overlap_count",
        search="_search_schedule_overlap_count",
    )

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

    enforcement_mode = fields.Selection(
        [("soft", "Warning"), ("hard", "Block")],
        default="soft",
        required=True,
        help="Soft: overlaps produce a warning. Hard: overlaps raise a validation error.",
    )

    origin_display = fields.Char(
        "Source",
        compute="_compute_origin_display",
    )

    _resource_schedule_idx = models.Index("(resource_id, date_start, date_end)")
    _origin_idx = models.Index("(res_model, res_id)")

    @api.constrains("date_start", "date_end")
    def _check_date_sanity(self):
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
        live = self.filtered(
            lambda r: r.active and r.resource_id and r.date_start and r.date_end
        )
        hard = live.filtered(lambda r: r.enforcement_mode == "hard")

        if live:
            self.env.cr.execute(
                "UPDATE resource_resource SET write_date = write_date"
                " WHERE id = ANY(%s)",
                (sorted(live.resource_id.ids),),
            )

        if live:
            windows_by_resource = defaultdict(lambda: [None, None])
            for record in live:
                window = windows_by_resource[record.resource_id.id]
                window[0] = (
                    record.date_start
                    if window[0] is None
                    else min(window[0], record.date_start)
                )
                window[1] = (
                    record.date_end
                    if window[1] is None
                    else max(window[1], record.date_end)
                )
            hard |= (
                self.sudo()
                .search(
                    Domain.AND(
                        [
                            Domain("id", "not in", live.ids),
                            Domain("active", "=", True),
                            Domain("enforcement_mode", "=", "hard"),
                            Domain.OR(
                                Domain.AND(
                                    [
                                        Domain("resource_id", "=", resource_id),
                                        Domain("date_start", "<", end),
                                        Domain("date_end", ">", start),
                                    ]
                                )
                                for resource_id, (
                                    start,
                                    end,
                                ) in windows_by_resource.items()
                            ),
                        ]
                    )
                )
                .with_env(self.env)
            )
        if not hard:
            return
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

    @api.depends("resource_id.company_id")
    def _compute_company_id(self):
        for record in self:
            record.company_id = (
                record.resource_id.company_id or record.company_id or self.env.company
            )

    @api.depends("resource_id", "resource_id.calendar_id", "company_id")
    def _compute_resource_calendar_id(self):
        for record in self:
            calendar = record.resource_id.calendar_id
            company = record.company_id or record.env.company
            if calendar and calendar.company_id and calendar.company_id != company:
                calendar = calendar.browse()
            record.resource_calendar_id = calendar or company.resource_calendar_id

    @api.depends(
        "date_start",
        "date_end",
        "resource_id",
        "resource_calendar_id",
        "allocated_percentage",
    )
    def _compute_allocated_hours(self):
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

        groups = defaultdict(self.browse)
        for record in dated - flexible:
            groups[record.resource_calendar_id] |= record

        attendance = self.env["resource.calendar.attendance"]
        for calendar, records in groups.items():
            window_start = localized(min(records.mapped("date_start")))
            window_end = localized(max(records.mapped("date_end")))

            if calendar:
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
        self.check_singleton()
        return round(work_hours * self.allocated_percentage / 100.0, 2)

    @api.depends(
        "date_start", "date_end", "resource_id", "allocated_percentage", "active"
    )
    def _compute_schedule_overlap_count(self):
        conflicts = self._conflicting_reservations()
        for record in self:
            record.schedule_overlap_count = len(conflicts[record.id])

    def _conflicting_reservations(self):
        stored = self.filtered(
            lambda r: (
                r.id
                and isinstance(r.id, int)
                and r.resource_id
                and r.date_start
                and r.date_end
            )
        )
        empty = self.browse()
        result = dict.fromkeys(self._ids, empty)
        if not stored:
            return result

        self.flush_model(self._OVERLAP_SWEEP_FIELDS)
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
            result[record.id] = self.browse(
                sorted(conflict_partners.get(record.id, ()))
            )
        return result

    def _overlap_rows(self, extra_conditions=()):
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
    def _prospective_conflicts(self, vals_list, ignore_ids=()):
        prospective = []
        for index, vals in enumerate(vals_list):
            resource_id = vals.get("resource_id")
            date_start, date_end = vals.get("date_start"), vals.get("date_end")
            if not resource_id or not date_start or not date_end:
                continue
            if date_end <= date_start:
                continue
            pct = vals.get("allocated_percentage")
            pct = 100.0 if pct is None else min(100.0, max(0.0, pct))
            prospective.append((-(index + 1), resource_id, date_start, date_end, pct))
        if not prospective:
            return self.browse()

        self.flush_model(self._OVERLAP_SWEEP_FIELDS)

        resource_ids = list({row[1] for row in prospective})
        window_start = min(row[2] for row in prospective)
        window_end = max(row[3] for row in prospective)
        conditions = [
            SQL("AND resource_id = ANY(%s)", resource_ids),
            SQL("AND date_start < %s", window_end),
            SQL("AND date_end > %s", window_start),
        ]
        if ignore_ids:
            conditions.append(SQL("AND id != ALL(%s)", list(ignore_ids)))
        rows_by_resource = self._overlap_rows(tuple(conditions))

        for sentinel, resource_id, date_start, date_end, pct in prospective:
            rows_by_resource[resource_id].append((sentinel, date_start, date_end, pct))

        partners = self._sweep_overlap_partners(rows_by_resource)
        conflicting = set()
        for sentinel, *_rest in prospective:
            conflicting.update(peer for peer in partners.get(sentinel, ()) if peer > 0)
        return self.browse(sorted(conflicting))

    @api.model
    def _search_schedule_overlap_count(self, operator, value):
        if operator not in COMPARATORS or not isinstance(value, int):
            return NotImplemented
        compare = COMPARATORS[operator]

        self.flush_model(self._OVERLAP_SWEEP_FIELDS)
        partners = self._sweep_overlap_partners(self._overlap_rows())
        conflicted = {res_id: len(peers) for res_id, peers in partners.items()}

        if compare(0, value):
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
        partners = defaultdict(set)
        for rows in rows_by_resource.values():
            events = []
            for res_id, date_start, date_end, pct in rows:
                if date_end <= date_start:
                    continue
                events.append((date_start, 1, res_id, pct))
                events.append((date_end, 0, res_id, pct))
            events.sort(key=lambda event: (event[0], event[1]))

            active = {}
            for _instant, kind, res_id, pct in events:
                if not kind:
                    active.pop(res_id, None)
                    continue
                active[res_id] = pct
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
        self.origin_display = False
        with_origin = self.filtered(lambda r: r.res_model and r.res_id)
        for model_name, records in with_origin.grouped("res_model").items():
            if model_name not in self.env:
                for record in records:
                    record.origin_display = f"{model_name},{record.res_id}"
                continue
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

    @api.autovacuum
    def _gc_orphan_reservations(self):
        reservations = self.sudo().with_context(active_test=False)
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

    def action_view_origin(self):
        self.check_singleton()
        if not self.res_model or not self.res_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "res_model": self.res_model,
            "res_id": self.res_id,
            "views": [(False, "form")],
            "target": "current",
        }

    @api.model
    def _sync_reservation(self, record, reservation_vals_list, existing=None):
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

        to_delete = self.browse().union(
            *(
                reservation
                for bucket in existing_by_resource.values()
                for reservation in bucket
            )
        )

        if to_delete:
            to_delete.sudo().unlink()
        created = self.sudo().create(to_create) if to_create else self.browse()

        return (existing - to_delete) | created

    @api.model
    def _reservation_intervals_batch(self, start_dt, end_dt, resources, domain=None):
        if not resources:
            return {}

        base_domain = [
            ("resource_id", "in", resources.ids),
            ("date_start", "<", end_dt.astimezone(UTC).replace(tzinfo=None)),
            ("date_end", ">", start_dt.astimezone(UTC).replace(tzinfo=None)),
            ("active", "=", True),
        ]
        if domain:
            base_domain += domain

        tuples_by_resource = defaultdict(list)
        for res in self.sudo().search(base_domain):
            tuples_by_resource[res.resource_id.id].append(
                (localized(res.date_start), localized(res.date_end), res)
            )

        return {
            resource.id: Intervals(tuples_by_resource.get(resource.id, []))
            for resource in resources
        }
