import itertools
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command, Domain
from odoo.libs.datetime import timezone
from odoo.libs.intervals import Intervals
from odoo.tools import float_is_zero, ormcache


class HrVersion(models.Model):
    _inherit = "hr.version"

    date_generated_from = fields.Datetime(
        string="Generated From",
        readonly=True,
        required=True,
        default=lambda self: datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ),
        groups="hr.group_hr_user",
        tracking=True,
    )
    date_generated_to = fields.Datetime(
        string="Generated To",
        readonly=True,
        required=True,
        default=lambda self: datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ),
        groups="hr.group_hr_user",
        tracking=True,
    )
    last_generation_date = fields.Date(
        string="Last Generation Date",
        readonly=True,
        groups="hr.group_hr_user",
        tracking=True,
    )
    work_entry_source = fields.Selection(
        [("calendar", "Working Schedule")],
        required=True,
        default="calendar",
        tracking=True,
        help="""
        Defines the source for work entries generation

        Working Schedule: Work entries will be generated from the working hours below.
        Attendances: Work entries will be generated from the employee's attendances. (requires Attendance app)
        Planning: Work entries will be generated from the employee's planning. (requires Planning app)
    """,
        groups="hr.group_hr_manager",
    )
    work_entry_source_calendar_invalid = fields.Boolean(
        compute="_compute_work_entry_source_calendar_invalid",
        groups="hr.group_hr_manager",
    )

    @api.depends("work_entry_source", "resource_calendar_id")
    def _compute_work_entry_source_calendar_invalid(self):
        for version in self:
            version.work_entry_source_calendar_invalid = (
                version.work_entry_source == "calendar"
                and not version.resource_calendar_id
            )

    @ormcache()
    def _get_default_work_entry_type_id(self):
        attendance = self.env.ref(
            "hr_work_entry.work_entry_type_attendance", raise_if_not_found=False
        )
        return attendance.id if attendance else False

    @ormcache()
    def _get_default_work_entry_type_overtime_id(self):
        attendance = self.env.ref(
            "hr_work_entry.work_entry_type_overtime", raise_if_not_found=False
        )
        return attendance.id if attendance else False

    def _get_leave_work_entry_type_dates(self, leave, date_from, date_to, employee):
        return self._get_leave_work_entry_type(leave)

    def _get_leave_work_entry_type(self, leave):
        return leave.work_entry_type_id

    def _get_more_vals_attendance_interval(self, interval):
        return []

    def _get_more_vals_leave_interval(self, interval, leaves):
        return []

    def _get_bypassing_work_entry_type_codes(self):
        return []

    def _get_interval_leave_work_entry_type(self, interval, leaves, bypassing_codes):
        self.check_singleton()
        for leave in leaves:
            if interval[0] >= leave[0] and interval[1] <= leave[1] and leave[2]:
                interval_start = interval[0].astimezone(UTC).replace(tzinfo=None)
                interval_stop = interval[1].astimezone(UTC).replace(tzinfo=None)
                return self._get_leave_work_entry_type_dates(
                    leave[2], interval_start, interval_stop, self.employee_id
                )
        return self.env.ref("hr_work_entry.work_entry_type_leave")

    def _get_sub_leave_domain(self):
        return Domain("calendar_id", "in", [False] + self.resource_calendar_id.ids)

    def _get_leave_domain(self, start_dt, end_dt):
        domain = Domain(
            [
                ("resource_id", "in", [False] + self.employee_id.resource_id.ids),
                ("date_from", "<=", end_dt.replace(tzinfo=None)),
                ("date_to", ">=", start_dt.replace(tzinfo=None)),
                ("company_id", "in", [False] + self.env.companies.ids),
            ]
        )
        return domain & self._get_sub_leave_domain()

    def _get_resource_calendar_leaves(self, start_dt, end_dt):
        return self.env["resource.calendar.leaves"].search(
            self._get_leave_domain(start_dt, end_dt)
        )

    def _get_attendance_intervals(self, start_dt, end_dt):
        assert start_dt.tzinfo and end_dt.tzinfo, "function expects localized date"
        employees_by_calendar = defaultdict(lambda: self.env["hr.employee"])
        for version in self:
            if version.work_entry_source != "calendar":
                continue
            employees_by_calendar[version.resource_calendar_id] |= version.employee_id
        result = {}
        for calendar, employees in employees_by_calendar.items():
            if not calendar:
                for employee in employees:
                    result.update(
                        {
                            employee.resource_id.id: Intervals(
                                [
                                    (
                                        start_dt,
                                        end_dt,
                                        self.env["resource.calendar.attendance"],
                                    )
                                ]
                            )
                        }
                    )
            else:
                result.update(
                    calendar._attendance_intervals_batch(
                        start_dt,
                        end_dt,
                        resources=employees.resource_id,
                        tz=timezone(calendar.tz) if calendar.tz else UTC,
                    )
                )
        return result

    def _get_interval_work_entry_type(self, interval):
        self.check_singleton()
        if "work_entry_type_id" in interval[2] and interval[2].work_entry_type_id[:1]:
            return interval[2].work_entry_type_id[:1]
        return self.env["hr.work.entry.type"].browse(
            self._get_default_work_entry_type_id()
        )

    def _get_valid_leave_intervals(self, attendances, interval):
        self.check_singleton()
        return [interval]

    @api.model
    def _get_whitelist_fields_from_template(self):
        return super()._get_whitelist_fields_from_template() + ["work_entry_source"]

    def _get_real_attendance_work_entry_vals(self, intervals):
        self.check_singleton()
        vals = []
        for interval in intervals:
            work_entry_type = self._get_interval_work_entry_type(interval)
            vals.append(
                {
                    **self._get_work_entry_vals(
                        "%s: %s" % (work_entry_type.name, self.employee_id.name),
                        interval[0],
                        interval[1],
                        work_entry_type,
                    ),
                    **dict(self._get_more_vals_attendance_interval(interval)),
                }
            )
        return vals

    @api.model
    def _split_intervals_per_record(self, intervals):
        split = []
        for start, stop, records in intervals:
            if records and len(records) > 1:
                split += [(start, stop, record) for record in records]
            else:
                split.append((start, stop, records))
        return split

    @api.model
    def _localize(self, dt, tz, tz_dates):
        if (tz, dt) not in tz_dates:
            tz_dates[tz, dt] = dt.astimezone(tz)
        return tz_dates[tz, dt]

    def _get_work_entry_vals(
        self, name, interval_start, interval_stop, work_entry_type
    ):
        self.ensure_one()
        return {
            "name": name,
            "date_start": interval_start.astimezone(UTC).replace(tzinfo=None),
            "date_stop": interval_stop.astimezone(UTC).replace(tzinfo=None),
            "work_entry_type_id": work_entry_type.id,
            "employee_id": self.employee_id.id,
            "version_id": self.id,
            "company_id": self.company_id.id,
        }

    def _get_version_leave_intervals(
        self, leaves_by_resource, attendances, start_dt, end_dt, tz_dates
    ):
        self.ensure_one()
        calendar = self.resource_calendar_id
        resource = self.employee_id.resource_id
        tz = (
            timezone(resource.tz)
            if self._is_fully_flexible()
            else timezone(calendar.tz)
        )
        resources_list = [self.env["resource.resource"], resource]
        leave_result = defaultdict(list)
        work_result = defaultdict(list)
        for leave in itertools.chain(
            leaves_by_resource[False], leaves_by_resource[resource.id]
        ):
            for res in resources_list:
                if (
                    res
                    and leave.calendar_id
                    and leave.calendar_id != calendar
                    and not leave.resource_id
                ):
                    continue
                tz = tz or timezone((res or self).tz)
                start = self._localize(start_dt, tz, tz_dates)
                end = self._localize(end_dt, tz, tz_dates)
                leave_interval = (
                    max(start, leave.date_from.astimezone(tz)),
                    min(end, leave.date_to.astimezone(tz)),
                    leave,
                )
                leave_interval = self._get_valid_leave_intervals(
                    attendances, leave_interval
                )
                if leave_interval:
                    if leave.time_type == "leave":
                        leave_result[res.id] += leave_interval
                    else:
                        work_result[res.id] += leave_interval
        return (
            Intervals(leave_result[resource.id], keep_distinct=True),
            Intervals(work_result[resource.id], keep_distinct=True),
            tz,
        )

    def _get_real_leave_intervals(
        self,
        attendances,
        plain_attendances,
        leaves,
        worked_leaves,
        start_dt,
        end_dt,
        tz,
    ):
        self.ensure_one()
        calendar = self.resource_calendar_id
        resource = self.employee_id.resource_id
        if not calendar:
            return leaves, worked_leaves

        if calendar.flexible_hours:
            one_day_leaves = Intervals(
                [l for l in leaves if l[0].date() == l[1].date()], keep_distinct=True
            )
            one_day_worked_leaves = Intervals(
                [l for l in worked_leaves if l[0].date() == l[1].date()],
                keep_distinct=True,
            )
            static_attendances = calendar._attendance_intervals_batch(
                start_dt, end_dt, resources=resource, tz=tz
            )[resource.id]
            return (
                (static_attendances & (leaves - one_day_leaves)) | one_day_leaves,
                (static_attendances & (worked_leaves - one_day_worked_leaves))
                | one_day_worked_leaves,
            )

        if self._has_static_work_entries() or not leaves:
            real_worked_leaves = attendances - plain_attendances - leaves
            return (
                attendances - plain_attendances - real_worked_leaves,
                real_worked_leaves,
            )

        static_attendances = calendar._attendance_intervals_batch(
            start_dt, end_dt, resources=resource, tz=tz
        )[resource.id]
        return static_attendances & leaves, static_attendances & worked_leaves

    def _get_worked_leave_work_entry_vals(
        self, intervals, worked_leaves, bypassing_codes
    ):
        self.ensure_one()
        vals = []
        for interval in intervals:
            work_entry_type = self._get_interval_leave_work_entry_type(
                interval, worked_leaves, bypassing_codes
            )
            vals.append(
                {
                    **self._get_work_entry_vals(
                        "%s: %s" % (work_entry_type.name, self.employee_id.name),
                        interval[0],
                        interval[1],
                        work_entry_type,
                    ),
                    "state": "draft",
                    **dict(self._get_more_vals_leave_interval(interval, worked_leaves)),
                }
            )
        return vals

    def _get_leave_work_entry_vals(self, real_leaves, leaves, bypassing_codes):
        self.ensure_one()
        vals = []
        leaves_over_attendances = Intervals(leaves, keep_distinct=True) & real_leaves
        for interval in real_leaves:
            if interval[0] == interval[1]:
                continue
            leaves_over_interval = [
                l
                for l in leaves_over_attendances
                if l[0] >= interval[0] and l[1] <= interval[1]
            ]
            for leave_interval in [
                (l[0], l[1], interval[2]) for l in leaves_over_interval
            ]:
                leave_entry_type = self._get_interval_leave_work_entry_type(
                    leave_interval, leaves, bypassing_codes
                )
                interval_leaves = [
                    leave
                    for leave in leaves
                    if leave[2].work_entry_type_id.id == leave_entry_type.id
                ]
                if not interval_leaves:
                    interval_leaves = leaves
                vals.append(
                    {
                        **self._get_work_entry_vals(
                            "%s%s"
                            % (
                                leave_entry_type.name + ": "
                                if leave_entry_type
                                else "",
                                self.employee_id.name,
                            ),
                            leave_interval[0],
                            leave_interval[1],
                            leave_entry_type,
                        ),
                        **dict(
                            self._get_more_vals_leave_interval(
                                interval, interval_leaves
                            )
                        ),
                    }
                )
        return vals

    def _get_version_work_entries_values(self, date_start, date_stop):
        start_dt = (
            date_start.replace(tzinfo=UTC) if not date_start.tzinfo else date_start
        )
        end_dt = date_stop.replace(tzinfo=UTC) if not date_stop.tzinfo else date_stop
        version_vals = []
        bypassing_codes = self._get_bypassing_work_entry_type_codes()

        attendances_by_resource = self.sudo()._get_attendance_intervals(
            start_dt, end_dt
        )

        leaves_by_resource = defaultdict(lambda: self.env["resource.calendar.leaves"])
        for leave in self._get_resource_calendar_leaves(start_dt, end_dt):
            leaves_by_resource[leave.resource_id.id] |= leave

        tz_dates = {}
        for version in self:
            resource = version.employee_id.resource_id
            attendances = attendances_by_resource.get(resource.id, Intervals([]))

            leaves, worked_leaves, tz = version._get_version_leave_intervals(
                leaves_by_resource, attendances, start_dt, end_dt, tz_dates
            )
            plain_attendances = attendances - leaves - worked_leaves
            real_leaves, real_worked_leaves = version._get_real_leave_intervals(
                attendances,
                plain_attendances,
                leaves,
                worked_leaves,
                start_dt,
                end_dt,
                tz,
            )
            real_attendances = self._get_real_attendances(
                attendances, leaves, worked_leaves
            )

            if not version._has_static_work_entries():
                real_attendances = self._split_intervals_per_record(real_attendances)
            leaves = self._split_intervals_per_record(leaves)
            real_worked_leaves = self._split_intervals_per_record(real_worked_leaves)

            version_vals += version._get_real_attendance_work_entry_vals(
                real_attendances
            )
            version_vals += version._get_worked_leave_work_entry_vals(
                real_worked_leaves, worked_leaves, bypassing_codes
            )
            version_vals += version._get_leave_work_entry_vals(
                real_leaves, leaves, bypassing_codes
            )
        return version_vals

    def _get_real_attendances(self, attendances, leaves, worked_leaves):
        return attendances - leaves - worked_leaves

    def _get_work_entries_values(self, date_start, date_stop):
        if isinstance(date_start, datetime):
            version_vals = self._get_version_work_entries_values(date_start, date_stop)
        else:
            version_vals = []
            versions_by_tz = defaultdict(lambda: self.env["hr.version"])
            for version in self:
                versions_by_tz[version.resource_calendar_id.tz] += version
            for version_tz, versions in versions_by_tz.items():
                tz = timezone(version_tz) if version_tz else UTC
                version_vals += versions._get_version_work_entries_values(
                    date_start.replace(tzinfo=tz), date_stop.replace(tzinfo=tz)
                )

        mapped_version_dates = defaultdict(lambda: ([], []))
        for x in version_vals:
            mapped_version_dates[x["version_id"]][0].append(x["date_start"])
            mapped_version_dates[x["version_id"]][1].append(x["date_stop"])

        for version in self:
            if version_vals:
                dates_stop = mapped_version_dates[version.id][1]
                if dates_stop:
                    date_stop_max = max(dates_stop)
                    version.date_generated_to = max(
                        version.date_generated_to, date_stop_max
                    )

                dates_start = mapped_version_dates[version.id][0]
                if dates_start:
                    date_start_min = min(dates_start)
                    version.date_generated_from = min(
                        version.date_generated_from, date_start_min
                    )

        return version_vals

    def _has_static_work_entries(self):
        self.check_singleton()
        return self.work_entry_source == "calendar"

    def generate_work_entries(
        self, date_start, date_stop, force=False, record_ids=None
    ):
        assert not isinstance(date_start, datetime)
        assert not isinstance(date_stop, datetime)

        date_start = datetime.combine(
            fields.Datetime.to_datetime(date_start), datetime.min.time()
        )
        date_stop = datetime.combine(
            fields.Datetime.to_datetime(date_stop), datetime.max.time()
        )

        versions_by_company_tz = defaultdict(lambda: self.env["hr.version"])
        for version in self:
            versions_by_company_tz[
                version.company_id,
                (version.resource_calendar_id or version.employee_id).tz,
            ] += version
        utc = timezone("UTC")
        new_work_entries = self.env["hr.work.entry"]
        for (company, version_tz), versions in versions_by_company_tz.items():
            tz = timezone(version_tz) if version_tz else utc
            date_start_tz = (
                date_start.replace(tzinfo=tz).astimezone(utc).replace(tzinfo=None)
            )
            date_stop_tz = (
                date_stop.replace(tzinfo=tz).astimezone(utc).replace(tzinfo=None)
            )
            new_work_entries += (
                versions.with_user(SUPERUSER_ID)
                .with_company(company)
                ._generate_work_entries(
                    date_start_tz, date_stop_tz, force=force, record_ids=record_ids
                )
            )
        return new_work_entries

    def _get_version_utc_bounds(self, tz, date_stop):
        self.ensure_one()
        version_start = (
            fields.Datetime.to_datetime(self.date_start)
            .replace(tzinfo=tz)
            .astimezone(UTC)
            .replace(tzinfo=None)
        )
        version_stop = (
            datetime.combine(
                fields.Datetime.to_datetime(self.date_end or date_stop),
                datetime.max.time(),
            )
            .replace(tzinfo=tz)
            .astimezone(UTC)
            .replace(tzinfo=None)
        )
        return version_start, version_stop

    def _get_expired_work_entries_domain(self, tz, version_stop, date_stop):
        self.ensure_one()
        if version_stop >= date_stop or (
            self.date_generated_from == self.date_generated_to
        ):
            return Domain(False)
        return Domain(
            [
                ("version_id", "=", self.id),
                ("date", ">", version_stop.replace(tzinfo=UTC).astimezone(tz)),
                ("date", "<=", date_stop.replace(tzinfo=UTC).astimezone(tz)),
                ("state", "!=", "validated"),
            ]
        )

    def _get_forced_work_entries_domain(self, tz, date_from, date_to, record_ids):
        self.ensure_one()
        domain = Domain(
            [
                ("version_id", "=", self.id),
                ("date", ">=", date_from.replace(tzinfo=UTC).astimezone(tz).date()),
                ("date", "<=", date_to.replace(tzinfo=UTC).astimezone(tz).date()),
                ("state", "!=", "validated"),
            ]
        )
        if record_ids:
            domain &= Domain("id", "in", record_ids)
        return domain

    def _plan_work_entry_generation(self, date_start, date_stop, force, record_ids):
        intervals_to_generate = defaultdict(lambda: self.env["hr.version"])
        domain_to_nullify = Domain(False)
        for tz, versions in self.grouped("tz").items():
            tz = timezone(tz) if tz else UTC
            for version in versions:
                version_start, version_stop = version._get_version_utc_bounds(
                    tz, date_stop
                )
                domain_to_nullify |= version._get_expired_work_entries_domain(
                    tz, version_stop, date_stop
                )
                if date_start > version_stop or date_stop < version_start:
                    continue
                date_from = max(date_start, version_start)
                date_to = min(date_stop, version_stop)

                if force:
                    domain_to_nullify |= version._get_forced_work_entries_domain(
                        tz, date_from, date_to, record_ids
                    )
                    if not record_ids:
                        intervals_to_generate[date_from, date_to] |= version
                    continue

                last_generated_from = min(version.date_generated_from, version_stop)
                if last_generated_from > date_from:
                    version.date_generated_from = date_from
                    intervals_to_generate[date_from, last_generated_from] |= version

                last_generated_to = max(version.date_generated_to, version_start)
                if last_generated_to < date_to:
                    version.date_generated_to = date_to
                    intervals_to_generate[last_generated_to, date_to] |= version
        return intervals_to_generate, domain_to_nullify

    def _generate_work_entries(
        self, date_start, date_stop, force=False, record_ids=None
    ):
        assert isinstance(date_start, datetime)
        assert isinstance(date_stop, datetime)
        self = self.with_context(tracking_disable=True)
        self.write({"last_generation_date": fields.Date.today()})
        self.filtered(lambda c: c.date_generated_from == c.date_generated_to).write(
            {"date_generated_from": date_start, "date_generated_to": date_start}
        )

        intervals_to_generate, domain_to_nullify = self._plan_work_entry_generation(
            date_start, date_stop, force, record_ids
        )

        vals_list = []
        for (date_from, date_to), versions in intervals_to_generate.items():
            vals_list.extend(versions._get_work_entries_values(date_from, date_to))

        if domain_to_nullify != Domain.FALSE:
            work_entry_null_vals = dict.fromkeys(
                self.env[
                    "hr.work.entry.regeneration.wizard"
                ]._work_entry_fields_to_nullify(),
                False,
            )
            self.env["hr.work.entry"].search(domain_to_nullify).write(
                work_entry_null_vals
            )

        if not vals_list:
            return self.env["hr.work.entry"]

        return self.env["hr.work.entry"].create(
            self._generate_work_entries_postprocess(vals_list)
        )

    @api.model
    def _generate_work_entries_postprocess_adapt_to_calendar(self, vals):
        if "work_entry_type_id" not in vals:
            return False
        return (
            self.env["hr.work.entry.type"].browse(vals["work_entry_type_id"]).is_leave
        )

    def _get_version_tz(self, version_id, tz_by_version):
        if version_id not in tz_by_version:
            version = self.env["hr.version"].browse(version_id)
            tz = (
                version.resource_calendar_id.tz
                or version.employee_id.resource_calendar_id.tz
                or version.company_id.resource_calendar_id.tz
            )
            if not tz:
                raise UserError(
                    self.env._("Missing timezone for work entries generation.")
                )
            tz_by_version[version_id] = timezone(tz)
        return tz_by_version[version_id]

    @api.model
    def _split_work_entry_vals_on_local_midnight(self, vals_list, tz_by_version):
        split_vals_list = []
        for vals in vals_list:
            vals = vals.copy()
            if not vals.get("date_start") or not vals.get("date_stop"):
                vals.pop("date_start", False)
                vals.pop("date_stop", False)
                if "duration" not in vals or "date" not in vals:
                    raise UserError(
                        self.env._("Missing date or duration on work entry")
                    )
                split_vals_list.append(vals)
                continue

            tz = self._get_version_tz(vals["version_id"], tz_by_version)
            local_start = self._as_utc(vals["date_start"]).astimezone(tz)
            local_stop = self._as_utc(vals["date_stop"]).astimezone(tz)

            current = (
                local_start + timedelta(microseconds=1)
                if local_start.time() == datetime.max.time()
                else local_start
            )
            while current < local_stop:
                next_local_midnight = (
                    datetime.combine(current.date() + timedelta(days=1), time.min)
                    - timedelta(microseconds=1)
                ).replace(tzinfo=tz)
                segment_end = min(local_stop, next_local_midnight)
                split_vals_list.append(
                    {
                        **vals,
                        "date_start": current.astimezone(UTC),
                        "date_stop": segment_end.astimezone(UTC),
                    }
                )
                current = segment_end + timedelta(microseconds=1)
        return split_vals_list

    @api.model
    def _as_utc(self, dt):
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)

    @api.model
    def _resolve_work_entry_vals_duration(self, vals_list, tz_by_version):
        cached_periods = {}
        mapped_periods = defaultdict(
            lambda: defaultdict(lambda: self.env["hr.employee"])
        )
        for vals in vals_list:
            if not vals.get("date_start") or not vals.get("date_stop"):
                continue
            period = (vals["date_start"], vals["date_stop"])
            tz = self._get_version_tz(vals["version_id"], tz_by_version)
            vals["date"] = period[0].astimezone(tz).date()
            version = self.env["hr.version"].browse(vals["version_id"])
            if not self._generate_work_entries_postprocess_adapt_to_calendar(vals):
                if "duration" in vals:
                    continue
                if period not in cached_periods:
                    cached_periods[period] = (
                        round((period[1] - period[0]).total_seconds()) / 3600
                    )
                vals["duration"] = cached_periods[period]
            elif not version.resource_calendar_id:
                vals["duration"] = 0.0
            else:
                mapped_periods[period][version.resource_calendar_id] |= (
                    version.employee_id
                )

        mapped_version_data = defaultdict(lambda: defaultdict(lambda: {"hours": 0.0}))
        for period, employees_by_calendar in mapped_periods.items():
            for calendar, employees in employees_by_calendar.items():
                mapped_version_data[period][calendar] = (
                    employees._get_work_days_data_batch(
                        period[0], period[1], compute_leaves=False, calendar=calendar
                    )
                )

        for vals in vals_list:
            if "duration" not in vals:
                period = (vals["date_start"], vals["date_stop"])
                version = self.env["hr.version"].browse(vals["version_id"])
                calendar = version.resource_calendar_id
                vals["duration"] = (
                    mapped_version_data[period][calendar][version.employee_id.id][
                        "hours"
                    ]
                    if calendar
                    else 0.0
                )
            vals.pop("date_start", False)
            vals.pop("date_stop", False)
        return vals_list

    @api.model
    def _merge_work_entry_vals(self, vals_list):
        merged_vals = {}
        for vals in vals_list:
            if float_is_zero(vals["duration"], 3):
                continue
            key = (
                vals["date"],
                vals.get("work_entry_type_id", False),
                vals["employee_id"],
                vals["version_id"],
                vals.get("company_id", False),
            )
            if key in merged_vals:
                merged_vals[key]["duration"] += vals.get("duration", 0.0)
            else:
                merged_vals[key] = vals.copy()
        return list(merged_vals.values())

    @api.model
    def _generate_work_entries_postprocess(self, vals_list):
        tz_by_version = {}
        vals_list = self._split_work_entry_vals_on_local_midnight(
            vals_list, tz_by_version
        )
        vals_list = self._resolve_work_entry_vals_duration(vals_list, tz_by_version)
        return self._merge_work_entry_vals(vals_list)

    def _remove_work_entries(self):
        all_we_to_unlink = self.env["hr.work.entry"]
        for version in self:
            date_start = fields.Datetime.to_datetime(version.date_start)
            if version.date_generated_from < date_start:
                we_to_remove = self.env["hr.work.entry"].search(
                    [("date", "<", date_start), ("version_id", "=", version.id)]
                )
                if we_to_remove:
                    version.date_generated_from = date_start
                    all_we_to_unlink |= we_to_remove
            if not version.date_end:
                continue
            date_end = datetime.combine(version.date_end, datetime.max.time())
            if version.date_generated_to > date_end:
                we_to_remove = self.env["hr.work.entry"].search(
                    [("date", ">", date_end), ("version_id", "=", version.id)]
                )
                if we_to_remove:
                    version.date_generated_to = date_end
                    all_we_to_unlink |= we_to_remove
        all_we_to_unlink.unlink()

    def _cancel_work_entries(self):
        if not self:
            return
        domains = []
        for version in self:
            date_start = fields.Datetime.to_datetime(version.date_start)
            version_domain = Domain(
                [
                    ("version_id", "=", version.id),
                    ("date", ">=", date_start),
                ]
            )
            if version.date_end:
                date_end = datetime.combine(version.date_end, datetime.max.time())
                version_domain &= Domain("date", "<=", date_end)
            domains.append(version_domain)
        domain = Domain.OR(domains) & Domain("state", "!=", "validated")
        work_entries = self.env["hr.work.entry"].sudo().search(domain)
        if work_entries:
            work_entries.unlink()

    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get("salary_simulation"):
            return result
        if (
            vals.get("contract_date_end")
            or vals.get("contract_date_start")
            or vals.get("date_version")
        ):
            self.sudo()._remove_work_entries()
        dependent_fields = self._get_fields_that_recompute_we()
        if any(key in dependent_fields for key in vals):
            for version_sudo in self.sudo():
                date_from = max(
                    version_sudo.date_start, version_sudo.date_generated_from.date()
                )
                date_to = min(
                    version_sudo.date_end or date.max,
                    version_sudo.date_generated_to.date(),
                )
                if date_from != date_to and version_sudo.employee_id:
                    version_sudo._recompute_work_entries(date_from, date_to)
        return result

    def unlink(self):
        self._cancel_work_entries()
        return super().unlink()

    def _recompute_work_entries(self, date_from, date_to):
        self.check_singleton()
        if self.employee_id:
            wizard = self.env["hr.work.entry.regeneration.wizard"].create(
                {
                    "employee_ids": [Command.set(self.employee_id.ids)],
                    "date_from": date_from,
                    "date_to": date_to,
                }
            )
            wizard.with_context(
                work_entry_skip_validation=True, active_test=False
            ).regenerate_work_entries()

    def _get_fields_that_recompute_we(self):
        return ["resource_calendar_id", "work_entry_source"]

    @api.model
    def _cron_generate_missing_work_entries(self):
        today = fields.Date.today()
        start = datetime.combine(today + relativedelta(day=1), time.min)
        stop = datetime.combine(today + relativedelta(months=1, day=31), time.max)
        all_versions = self.env[
            "hr.employee"
        ]._get_all_versions_with_contract_overlap_with_period(start.date(), stop.date())
        versions_todo = all_versions.filtered(
            lambda v: (
                (v.date_generated_from > start or v.date_generated_to < stop)
                and (not v.last_generation_date or v.last_generation_date < today)
            )
        )
        if not versions_todo:
            return
        version_todo_count = len(versions_todo)
        versions_todo = versions_todo.filtered(
            lambda v: v.company_id == versions_todo[0].company_id
        )
        BATCH_SIZE = 100
        versions_todo = versions_todo.sorted(
            key=lambda v: 1 if v._has_static_work_entries() else 100
        )
        versions_todo[:BATCH_SIZE].generate_work_entries(
            start.date(), stop.date(), False
        )
        if version_todo_count > BATCH_SIZE:
            self.env.ref(
                "hr_work_entry.ir_cron_generate_missing_work_entries"
            )._trigger()
