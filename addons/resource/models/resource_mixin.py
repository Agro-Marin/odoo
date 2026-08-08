from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self

from odoo import api, fields, models
from odoo.models import ValuesType
from odoo.tools.date_utils import localized

if TYPE_CHECKING:
    from .resource_calendar import ResourceCalendar


class ResourceMixin(models.AbstractModel):
    _name = "resource.mixin"
    _description = "Resource Mixin"

    resource_id = fields.Many2one(
        "resource.resource",
        "Resource",
        bypass_search_access=True,
        index=True,
        ondelete="restrict",
        required=True,
    )
    tz = fields.Selection(
        related="resource_id.tz",
        string="Timezone",
        readonly=False,
        help="This field is used in order to define in which timezone the resources will work.",
    )
    # These two are *related* to the resource, writable and stored, so their
    # defaults are not inert fallbacks: whatever they produce is written
    # straight through onto the resource.  That is wanted when this record
    # creates its own resource, and wrong when it attaches to an existing one --
    # see ``create``, which pins both from the resource in that case so the
    # default never fires and cannot repoint someone else's schedule.
    company_id = fields.Many2one(
        "res.company",
        "Company",
        default=lambda self: self.env.company,
        index=True,
        related="resource_id.company_id",
        precompute=True,
        store=True,
        readonly=False,
    )
    resource_calendar_id = fields.Many2one(
        "resource.calendar",
        "Working Hours",
        default=lambda self: self.env.company.resource_calendar_id,
        index=True,
        related="resource_id.calendar_id",
        store=True,
        readonly=False,
    )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        resources_vals_list = []
        calendar_ids = [
            vals["resource_calendar_id"]
            for vals in vals_list
            if vals.get("resource_calendar_id")
        ]
        calendars_tz = {
            calendar.id: calendar.tz
            for calendar in self.env["resource.calendar"].browse(calendar_ids)
        }
        for vals in vals_list:
            if not vals.get("resource_id"):
                resources_vals_list.append(  # noqa: PERF401 — vals.pop() side effect
                    self._prepare_resource_values(
                        vals,
                        vals.pop("tz", False)
                        or calendars_tz.get(vals.get("resource_calendar_id")),
                    )
                )
        if resources_vals_list:
            resources = self.env["resource.resource"].create(resources_vals_list)
            resources_iter = iter(resources.ids)
            for vals in vals_list:
                if not vals.get("resource_id"):
                    vals["resource_id"] = next(resources_iter)

        # Attaching to a resource somebody else owns: pin the two related,
        # writable, stored fields from that resource so the field defaults never
        # run.  A default here is not a fallback -- it is an explicit value the
        # ORM writes through the relation, so it would repoint the resource's
        # company and calendar to the acting user's, silently handing a
        # company-A resource company-B's schedule.  This runs before
        # ``super().create()``, which is where ``_add_missing_default_values``
        # would otherwise fill them in.
        attached = [
            vals
            for vals in vals_list
            if vals.get("resource_id")
            and not ("company_id" in vals and "resource_calendar_id" in vals)
        ]
        if attached:
            # ``exists()`` so a stale id falls through to the foreign key, which
            # names the real problem, rather than dying on a lookup here.
            resources_by_id = {
                resource.id: resource
                for resource in self.env["resource.resource"]
                .browse([vals["resource_id"] for vals in attached])
                .exists()
            }
            for vals in attached:
                resource = resources_by_id.get(vals["resource_id"])
                if not resource:
                    continue
                vals.setdefault("company_id", resource.company_id.id)
                vals.setdefault("resource_calendar_id", resource.calendar_id.id)
        return super(ResourceMixin, self.with_context(check_idempotence=True)).create(
            vals_list
        )

    def _prepare_resource_values(self, vals: ValuesType, tz: str | bool) -> ValuesType:
        resource_vals = {"name": vals.get(self._rec_name)}
        if tz:
            resource_vals["tz"] = tz
        company_id = vals.get("company_id", self.env.company.id)
        if company_id:
            resource_vals["company_id"] = company_id
        calendar_id = vals.get("resource_calendar_id")
        if calendar_id:
            resource_vals["calendar_id"] = calendar_id
        return resource_vals

    def copy_data(self, default: ValuesType | None = None) -> list[ValuesType]:
        default = dict(default or {})
        vals_list = super().copy_data(default=default)

        resource_default = {}
        if "company_id" in default:
            resource_default["company_id"] = default["company_id"]
        if "resource_calendar_id" in default:
            resource_default["calendar_id"] = default["resource_calendar_id"]
        resources = [record.resource_id for record in self]
        resources_to_copy = self.env["resource.resource"].concat(*resources)
        new_resources = resources_to_copy.copy(resource_default)
        for resource, vals in zip(new_resources, vals_list, strict=True):
            vals["resource_id"] = resource.id
            vals["company_id"] = resource.company_id.id
            vals["resource_calendar_id"] = resource.calendar_id.id
        return vals_list

    def _get_calendars(
        self, date_from: datetime | None = None
    ) -> dict[int, ResourceCalendar]:
        return {resource.id: resource.resource_calendar_id for resource in self}

    def _get_work_days_data_batch(
        self,
        from_datetime: datetime,
        to_datetime: datetime,
        compute_leaves: bool = True,
        calendar: ResourceCalendar | None = None,
        domain: list | None = None,
    ) -> dict[int, dict[str, float]]:
        """
        By default the resource calendar is used, but it can be
        changed using the `calendar` argument.

        `domain` is used in order to recognise the leaves to take,
        None means default value ('time_type', '=', 'leave')

        Returns a dict {'days': n, 'hours': h} containing the
        quantity of working time expressed as days and as hours.
        """
        records_per_resource = self._records_per_resource()
        result = {}

        # naive datetimes are made explicit in UTC
        from_datetime = localized(from_datetime)
        to_datetime = localized(to_datetime)

        if calendar:
            mapped_resources = {calendar: self.resource_id}
        else:
            calendar_by_resource = self._get_calendars(from_datetime)
            mapped_resources = defaultdict(lambda: self.env["resource.resource"])
            for resource in self:
                mapped_resources[calendar_by_resource[resource.id]] |= (
                    resource.resource_id
                )

        for calendar, calendar_resources in mapped_resources.items():  # noqa: PLR1704
            if not calendar:
                for calendar_resource in calendar_resources:
                    result[calendar_resource.id] = {"days": 0, "hours": 0}
                continue

            # actual hours per day
            if compute_leaves:
                intervals = calendar._work_intervals_batch(
                    from_datetime, to_datetime, calendar_resources, domain
                )
            else:
                intervals = calendar._attendance_intervals_batch(
                    from_datetime, to_datetime, calendar_resources
                )

            for calendar_resource in calendar_resources:
                result[calendar_resource.id] = (
                    calendar._get_attendance_intervals_days_data(
                        intervals[calendar_resource.id]
                    )
                )

        # convert "resource: result" into "record: result"
        return self._fan_out_per_record(result, records_per_resource)

    def _records_per_resource(self) -> dict[int, list[int]]:
        """Group this recordset's ids by the resource they point at.

        Nothing in the data model forbids two records sharing one
        ``resource.resource`` -- there is no unique constraint, and creating a
        second ``hr.employee`` on an existing resource is accepted.  The day-data
        helpers below used to build ``{resource_id: record_id}``, so the second
        record to name a resource overwrote the first and then vanished from the
        returned dict, leaving callers that index by record id with a
        ``KeyError`` and no hint as to why.
        """
        grouped = defaultdict(list)
        for record in self:
            grouped[record.resource_id.id].append(record.id)
        return grouped

    @staticmethod
    def _fan_out_per_record(
        result_per_resource: dict[int, dict[str, float]],
        records_per_resource: dict[int, list[int]],
    ) -> dict[int, dict[str, float]]:
        """Re-key a per-resource result onto every record that holds it."""
        return {
            record_id: result_per_resource[resource_id]
            for resource_id, record_ids in records_per_resource.items()
            for record_id in record_ids
            if resource_id in result_per_resource
        }

    def _get_leave_days_data_batch(
        self,
        from_datetime: datetime,
        to_datetime: datetime,
        calendar: ResourceCalendar | None = None,
        domain: list | None = None,
    ) -> dict[int, dict[str, float]]:
        """
        By default the resource calendar is used, but it can be
        changed using the `calendar` argument.

        `domain` is used in order to recognise the leaves to take,
        None means default value ('time_type', '=', 'leave')

        Returns a dict {'days': n, 'hours': h} containing the number of leaves
        expressed as days and as hours.
        """
        records_per_resource = self._records_per_resource()
        result = {}

        # naive datetimes are made explicit in UTC
        from_datetime = localized(from_datetime)
        to_datetime = localized(to_datetime)

        mapped_resources = defaultdict(lambda: self.env["resource.resource"])
        for record in self:
            mapped_resources[calendar or record.resource_calendar_id] |= (
                record.resource_id
            )

        for calendar, calendar_resources in mapped_resources.items():  # noqa: PLR1704
            # handle fully flexible resources by returning the length of the whole interval
            # since we do not take into account leaves for fully flexible resources
            if not calendar:
                # Count calendar days inclusively.  ``timedelta.days`` truncates,
                # so a leave covering one whole day (00:00 to 23:59:59) measured
                # **zero** days and a five-day span measured four -- always one
                # short, and never right for any window that does not end
                # exactly on a midnight.
                days = (to_datetime.date() - from_datetime.date()).days + 1
                hours = (to_datetime - from_datetime).total_seconds() / 3600
                for calendar_resource in calendar_resources:
                    result[calendar_resource.id] = {"days": days, "hours": hours}
                continue

            # compute actual hours per day
            attendances = calendar._attendance_intervals_batch(
                from_datetime, to_datetime, calendar_resources
            )
            leaves = calendar._leave_intervals_batch(
                from_datetime, to_datetime, calendar_resources, domain
            )

            for calendar_resource in calendar_resources:
                result[calendar_resource.id] = (
                    calendar._get_attendance_intervals_days_data(
                        attendances[calendar_resource.id] & leaves[calendar_resource.id]
                    )
                )

        # convert "resource: result" into "record: result"
        return self._fan_out_per_record(result, records_per_resource)

    def _adjust_to_calendar(self, start: datetime, end: datetime) -> dict:
        resource_results = self.resource_id._adjust_to_calendar(start, end)
        # change dict keys from resources to associated records.
        return {record: resource_results[record.resource_id] for record in self}

    def _list_work_time_per_day(
        self,
        from_datetime: datetime,
        to_datetime: datetime,
        calendar: ResourceCalendar | None = None,
        domain: list | None = None,
    ) -> dict[int, list[tuple]]:
        """
        By default the resource calendar is used, but it can be
        changed using the `calendar` argument.

        `domain` is used in order to recognise the leaves to take,
        None means default value ('time_type', '=', 'leave')

        Returns a list of tuples (day, hours) for each day
        containing at least an attendance.
        """
        result = {}
        records_by_calendar = defaultdict(lambda: self.env[self._name])
        for record in self:
            records_by_calendar[
                calendar
                or record.resource_calendar_id
                or record.company_id.resource_calendar_id
            ] += record

        # naive datetimes are made explicit in UTC
        if not from_datetime.tzinfo:
            from_datetime = from_datetime.replace(tzinfo=UTC)
        if not to_datetime.tzinfo:
            to_datetime = to_datetime.replace(tzinfo=UTC)
        compute_leaves = self.env.context.get("compute_leaves", True)

        for calendar, records in records_by_calendar.items():  # noqa: PLR1704
            if not calendar:
                for record in records:
                    result[record.id] = []
                continue
            resources = records.resource_id
            all_intervals = calendar._work_intervals_batch(
                from_datetime,
                to_datetime,
                resources,
                domain,
                compute_leaves=compute_leaves,
            )
            for record in records:
                intervals = all_intervals[record.resource_id.id]
                record_result = defaultdict(float)
                for start, stop, _meta in intervals:
                    record_result[start.date()] += (stop - start).total_seconds() / 3600
                result[record.id] = sorted(record_result.items())
        return result

    def list_leaves(
        self,
        from_datetime: datetime,
        to_datetime: datetime,
        calendar: ResourceCalendar | None = None,
        domain: list | None = None,
    ) -> list[tuple]:
        """
        By default the resource calendar is used, but it can be
        changed using the `calendar` argument.

        `domain` is used in order to recognise the leaves to take,
        None means default value ('time_type', '=', 'leave')

        Returns a list of tuples (day, hours, resource.calendar.leaves)
        for each leave in the calendar.
        """
        # Single-record only: the body indexes the per-resource interval dicts
        # with ``resource.id``.  Without this the failure surfaced deep in the
        # calendar layer as a bare ``Expected singleton``, naming
        # ``resource.resource`` rather than the model actually called.
        self.ensure_one()
        resource = self.resource_id
        calendar = calendar or self.resource_calendar_id

        # naive datetimes are made explicit in UTC
        if not from_datetime.tzinfo:
            from_datetime = from_datetime.replace(tzinfo=UTC)
        if not to_datetime.tzinfo:
            to_datetime = to_datetime.replace(tzinfo=UTC)

        attendances = calendar._attendance_intervals_batch(
            from_datetime, to_datetime, resource
        )[resource.id]
        leaves = calendar._leave_intervals_batch(
            from_datetime, to_datetime, resource, domain
        )[resource.id]
        result = []
        for start, stop, leave in leaves & attendances:
            hours = (stop - start).total_seconds() / 3600
            result.append((start.date(), hours, leave))
        return result
