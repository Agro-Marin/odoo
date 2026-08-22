from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from functools import partial
from itertools import chain
from typing import TYPE_CHECKING, Any, NamedTuple

from dateutil.relativedelta import relativedelta
from dateutil.rrule import DAILY, rrule
from zoneinfo import ZoneInfo


from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Command, Domain
from odoo.libs.intervals import Intervals
from odoo.libs.numbers import float_round
from odoo.models import ValuesType
from odoo.tools import SQL, date_utils, float_compare
from odoo.tools.date_utils import float_to_time, localized, to_timezone

from .utils import HOURS_PER_DAY
from odoo.addons.base.models.res_partner import _tz_get
from odoo.libs.datetime import timezone

if TYPE_CHECKING:
    from .resource_calendar_attendance import ResourceCalendarAttendance
    from .resource_resource import ResourceResource


class DummyAttendance(NamedTuple):
    hour_from: float
    hour_to: float
    dayofweek: str
    day_period: str | None
    week_type: str | None


# ``plan_hours`` / ``plan_days`` scan forward (or backward) one fixed window at
# a time, giving up after a bounded number of windows so a request that can
# never be satisfied (e.g. hours on a calendar with no attendances) terminates
# instead of looping forever.  14-day windows × 100 iterations ≈ 3.8 years.
_PLAN_WINDOW = timedelta(days=14)
_PLAN_MAX_ITERATIONS = 100


class ResourceCalendar(models.Model):
    """Calendar model for a resource. It has

    - attendance_ids: list of resource.calendar.attendance that are a working
                    interval in a given weekday.
    - leave_ids: list of leaves linked to this calendar. A leave can be general
                or linked to a specific resource, depending on its resource_id.

    All methods in this class use intervals. An interval is a tuple holding
    (begin_datetime, end_datetime). A list of intervals is therefore a list of
    tuples, holding several intervals of work or leaves."""

    _name = "resource.calendar"
    _description = "Resource Working Time"

    @api.model
    def default_get(self, fields: list[str]) -> dict[str, Any]:
        res = super().default_get(fields)
        if not res.get("name") and res.get("company_id"):
            res["name"] = self.env._(
                "Working Hours of %s",
                self.env["res.company"].browse(res["company_id"]).name,
            )
        if "attendance_ids" in fields and not res.get("attendance_ids"):
            company_id = res.get("company_id", self.env.company.id)
            company = self.env["res.company"].browse(company_id)
            res["attendance_ids"] = self._get_default_attendance_ids(company)
            res["two_weeks_calendar"] = company.resource_calendar_id.two_weeks_calendar
        if "full_time_required_hours" in fields and not res.get(
            "full_time_required_hours"
        ):
            company_id = res.get("company_id", self.env.company.id)
            company = self.env["res.company"].browse(company_id)
            res["full_time_required_hours"] = (
                company.resource_calendar_id.full_time_required_hours
            )
        return res

    name = fields.Char(required=True)
    active = fields.Boolean(
        "Active",
        default=True,
        help="If the active field is set to false, it will allow you to hide the Working Time without removing it.",
    )
    attendance_ids = fields.One2many(
        "resource.calendar.attendance",
        "calendar_id",
        "Working Time",
        compute="_compute_attendance_ids",
        store=True,
        readonly=False,
        copy=True,
    )
    attendance_ids_1st_week = fields.One2many(
        "resource.calendar.attendance",
        "calendar_id",
        "Working Time 1st Week",
        compute="_compute_two_weeks_attendance",
        inverse="_inverse_two_weeks_calendar",
    )
    attendance_ids_2nd_week = fields.One2many(
        "resource.calendar.attendance",
        "calendar_id",
        "Working Time 2nd Week",
        compute="_compute_two_weeks_attendance",
        inverse="_inverse_two_weeks_calendar",
    )
    company_id = fields.Many2one(
        "res.company",
        "Company",
        domain=lambda self: [("id", "in", self.env.companies.ids)],
        default=lambda self: self.env.company,
        index="btree_not_null",
    )
    leave_ids = fields.One2many("resource.calendar.leaves", "calendar_id", "Time Off")
    resource_ids = fields.One2many(
        "resource.resource",
        "calendar_id",
        "Work Resources",
    )
    schedule_type = fields.Selection(
        [
            ("flexible", "Flexible"),
            ("fully_fixed", "Fully Fixed"),
        ],
        string="Schedule Type",
        required=True,
        default="fully_fixed",
        help="Choose which level of definition you want to define on your Schedule\n"
        "- Flexible : Define an amount of hours to work on the week.\n"
        "- Fully Fixed : define the days, periods and the start & end time for each period of the day",
    )
    duration_based = fields.Boolean(
        "Attendance based on duration",
        help="The hours will be centered around 12:00 to cover the duration for the day",
    )
    flexible_hours = fields.Boolean(
        string="Flexible Hours",
        compute="_compute_flexible_hours",
        inverse="_inverse_flexible_hours",
        store=True,
        help="When enabled, it will allow employees to work flexibly, without relying on the company's working schedule (working hours).",
    )
    full_time_required_hours = fields.Float(
        string="Full Time Equivalent",
        compute="_compute_full_time_required_hours",
        store=True,
        readonly=False,
        help="Number of hours to work on the company schedule to be considered as fulltime.",
    )
    global_leave_ids = fields.One2many(
        "resource.calendar.leaves",
        "calendar_id",
        "Global Time Off",
        compute="_compute_global_leave_ids",
        store=True,
        readonly=False,
        domain=[("resource_id", "=", False)],
        copy=True,
    )
    hours_per_day = fields.Float(
        "Average Hour per Day",
        store=True,
        compute="_compute_hours_per_day",
        digits=(2, 2),
        readonly=False,
        help="Average hours per day a resource is supposed to work with this calendar.",
    )
    hours_per_week = fields.Float(
        string="Hours per Week",
        compute="_compute_hours_per_week",
        store=True,
        readonly=False,
        copy=False,
    )
    is_fulltime = fields.Boolean(
        compute="_compute_work_time", string="Is Full Time"
    )
    two_weeks_calendar = fields.Boolean(string="Calendar in 2 weeks mode")
    two_weeks_explanation = fields.Char(
        "Explanation", compute="_compute_two_weeks_explanation"
    )

    def _default_tz(self):
        admin = self.env.ref("base.user_admin", raise_if_not_found=False)
        return (
            self.env.context.get("tz")
            or self.env.user.tz
            or (admin and admin.tz)
            or "UTC"
        )

    tz = fields.Selection(
        _tz_get,
        string="Timezone",
        required=True,
        default=lambda self: self._default_tz(),
        help="This field is used in order to define in which timezone the resources will work.",
    )
    tz_offset = fields.Char(compute="_compute_tz_offset", string="Timezone offset")
    work_resources_count = fields.Integer(
        "Work Resources count", compute="_compute_work_resources_count"
    )
    work_time_rate = fields.Float(
        string="Work Time Rate",
        compute="_compute_work_time",
        search="_search_work_time_rate",
        help="Work time rate versus full time working schedule, should be between 0 and 100 %.",
    )

    # --------------------------------------------------
    # Constrains
    # --------------------------------------------------

    @api.constrains("attendance_ids")
    def _check_attendance_ids(self):
        for res_calendar in self:
            if (
                res_calendar.two_weeks_calendar
                and res_calendar.attendance_ids.filtered(
                    lambda a: a.display_type == "line_section"
                )
                and not res_calendar.attendance_ids.sorted("sequence")[0].display_type
            ):
                raise ValidationError(
                    self.env._(
                        "In a calendar with 2 weeks mode, all periods need to be in the sections."
                    )
                )

            # Avoid superimpose in attendance
            attendance_ids = res_calendar.attendance_ids.filtered(
                lambda attendance: not attendance.display_type
            )
            if res_calendar.two_weeks_calendar:
                res_calendar._check_overlap(
                    attendance_ids.filtered(
                        lambda attendance: attendance.week_type == "0"
                    )
                )
                res_calendar._check_overlap(
                    attendance_ids.filtered(
                        lambda attendance: attendance.week_type == "1"
                    )
                )
            else:
                res_calendar._check_overlap(attendance_ids)

    # --------------------------------------------------
    # Compute Methods
    # --------------------------------------------------

    @api.depends("two_weeks_calendar")
    def _compute_two_weeks_attendance(self):
        for calendar in self:
            if not calendar.two_weeks_calendar:
                calendar.attendance_ids_1st_week = False
                calendar.attendance_ids_2nd_week = False
                continue
            calendar.attendance_ids_1st_week = calendar.attendance_ids.filtered(
                lambda a: a.week_type == "0"
            )
            calendar.attendance_ids_2nd_week = calendar.attendance_ids.filtered(
                lambda a: a.week_type == "1"
            )

    def _inverse_two_weeks_calendar(self):
        for calendar in self:
            if not calendar.two_weeks_calendar:
                continue
            calendar.attendance_ids = (
                calendar.attendance_ids_1st_week + calendar.attendance_ids_2nd_week
            )

    @api.depends("hours_per_week", "company_id.resource_calendar_id.hours_per_week")
    def _compute_full_time_required_hours(self):
        for calendar in self.filtered("company_id"):
            calendar.full_time_required_hours = (
                calendar.company_id.resource_calendar_id.hours_per_week
            )

    @api.depends("schedule_type")
    def _compute_flexible_hours(self):
        for calendar in self:
            calendar.flexible_hours = calendar.schedule_type == "flexible"

    def _inverse_flexible_hours(self):
        for calendar in self:
            calendar.schedule_type = (
                "flexible" if calendar.flexible_hours else "fully_fixed"
            )

    @api.depends("company_id")
    def _compute_attendance_ids(self):
        for calendar in self.filtered(
            lambda c: (
                not c._origin or (c._origin.company_id != c.company_id and c.company_id)
            )
        ):
            company_calendar = calendar.company_id.resource_calendar_id
            calendar.update(
                {
                    "two_weeks_calendar": company_calendar.two_weeks_calendar,
                    "tz": company_calendar.tz,
                    "attendance_ids": [Command.clear()]
                    + [
                        Command.create(attendance._copy_attendance_vals())
                        for attendance in company_calendar.attendance_ids
                    ],
                }
            )

    @api.onchange("attendance_ids")
    def _onchange_attendance_ids(self):
        if not self.two_weeks_calendar:
            return

        even_week_seq = self.attendance_ids.filtered(
            lambda att: att.display_type == "line_section" and att.week_type == "0"
        )
        odd_week_seq = self.attendance_ids.filtered(
            lambda att: att.display_type == "line_section" and att.week_type == "1"
        )
        if len(even_week_seq) != 1 or len(odd_week_seq) != 1:
            raise ValidationError(self.env._("You can't delete section between weeks."))

        even_week_seq = even_week_seq.sequence
        odd_week_seq = odd_week_seq.sequence

        for line in self.attendance_ids.filtered(lambda att: att.display_type is False):
            if even_week_seq > odd_week_seq:
                line.week_type = "1" if even_week_seq > line.sequence else "0"
            else:
                line.week_type = "0" if odd_week_seq > line.sequence else "1"

    @api.depends("company_id")
    def _compute_global_leave_ids(self):
        for calendar in self.filtered(
            lambda c: not c._origin or c._origin.company_id != c.company_id
        ):
            calendar.update(
                {
                    "global_leave_ids": [Command.clear()]
                    + [
                        Command.create(leave._copy_leave_vals())
                        for leave in calendar.company_id.resource_calendar_id.global_leave_ids
                    ],
                }
            )

    @api.depends(
        "attendance_ids",
        "attendance_ids.hour_from",
        "attendance_ids.hour_to",
        "two_weeks_calendar",
        "flexible_hours",
    )
    def _compute_hours_per_day(self):
        """Compute the average hours per day.
        Cannot directly depend on hours_per_week because of rounding issues."""
        for calendar in self.filtered(lambda c: not c.flexible_hours):
            calendar.hours_per_day = float_round(
                calendar._get_hours_per_day(), precision_digits=2
            )

    @api.depends(
        "attendance_ids",
        "attendance_ids.hour_from",
        "attendance_ids.hour_to",
        "two_weeks_calendar",
        "flexible_hours",
    )
    def _compute_hours_per_week(self):
        """Compute the average hours per week"""
        for calendar in self.filtered(lambda c: not c.flexible_hours):
            calendar.hours_per_week = float_round(
                calendar._get_hours_per_week(), precision_digits=2
            )

    def _compute_two_weeks_explanation(self):
        # No ``@api.depends``: the sentence is the same for every calendar and
        # varies only with the wall clock, which no dependency can express.  It
        # used to declare ``two_weeks_calendar``, which is not something the value
        # reads.
        #
        # ``context_today``, not ``Date.today()``: the latter is the *server's*
        # local date, while the section labels rendered directly beneath this
        # sentence come from ``resource.calendar.attendance._compute_display_name``,
        # which uses the user's.  Around midnight the two disagreed and the form
        # contradicted itself.
        today = fields.Date.context_today(self)
        week_type = self.env["resource.calendar.attendance"].get_week_type(today)
        # Name the week the way the calendar itself does.  This used to read
        # "odd"/"even", a second vocabulary for the very same thing: the form
        # below labels its sections "First week" / "Second week", and nothing
        # told the reader that "odd" meant the first one.
        week_type_str = (
            self.env._("the second") if week_type else self.env._("the first")
        )
        first_day = date_utils.start_of(today, "week")
        last_day = date_utils.end_of(today, "week")
        explanation = self.env._(
            "The current week (from %(first_day)s to %(last_day)s) is %(number)s week.",
            first_day=first_day,
            last_day=last_day,
            number=week_type_str,
        )
        for calendar in self:
            calendar.two_weeks_explanation = explanation

    @api.depends("tz")
    def _compute_tz_offset(self):
        for calendar in self:
            calendar.tz_offset = datetime.now(timezone(calendar.tz or "GMT")).strftime(
                "%z"
            )

    @api.depends("resource_ids")
    def _compute_work_resources_count(self):
        resources_per_calendar = dict(
            self.env["resource.resource"]._read_group(
                domain=[("calendar_id", "in", self.ids)],
                groupby=["calendar_id"],
                aggregates=["__count"],
            )
        )
        for calendar in self:
            calendar.work_resources_count = resources_per_calendar.get(calendar, 0)

    @api.depends("hours_per_week", "full_time_required_hours")
    def _compute_work_time(self):
        for calendar in self:
            if calendar.full_time_required_hours:
                calendar.work_time_rate = (
                    calendar.hours_per_week / calendar.full_time_required_hours * 100
                )
            else:
                calendar.work_time_rate = 100

            calendar.is_fulltime = (
                float_compare(
                    calendar.full_time_required_hours, calendar.hours_per_week, 3
                )
                == 0
            )

    # SQL mirror of the ``_compute_work_time`` formula, kept as the single
    # source of truth for the pushed-down search below.  Keep the two in sync.
    _WORK_TIME_RATE_SQL = SQL(
        "CASE WHEN COALESCE(full_time_required_hours, 0) > 0"
        " THEN hours_per_week / full_time_required_hours * 100"
        " ELSE 100 END"
    )

    @api.model
    def _search_work_time_rate(self, operator, value):
        """Search calendars by work time rate using SQL on stored fields.

        ``work_time_rate`` is ``hours_per_week / full_time_required_hours * 100``
        (or 100 when ``full_time_required_hours`` is zero).  Both operands are
        stored, so the filter is pushed down to SQL instead of loading every
        calendar into Python.
        """
        # Whitelisted scalar comparison operators → fixed SQL fragments (no
        # operator string ever reaches the query except through this map).
        scalar_ops = {op: SQL(op) for op in ("<", ">", "<=", ">=", "=", "!=")}
        rate = self._WORK_TIME_RATE_SQL
        if operator in scalar_ops:
            if not isinstance(value, int | float):
                return NotImplemented
            condition = SQL("%s %s %s", rate, scalar_ops[operator], value)
        elif operator in ("in", "not in"):
            if not all(isinstance(v, int | float) for v in value):
                return NotImplemented
            values = list(value)
            condition = (
                SQL("%s = ANY(%s)", rate, values)
                if operator == "in"
                else SQL("%s != ALL(%s)", rate, values)
            )
        else:
            return NotImplemented

        # This reads the stored ``hours_per_week`` / ``full_time_required_hours``
        # columns straight from the table during domain optimisation, before the
        # ORM would flush them for the outer query.  Flush pending recomputes
        # first, otherwise a freshly created/edited calendar whose rate hasn't
        # hit the DB yet would be silently mis-filtered (same guard as the
        # reservation overlap sweep).
        self.flush_model(["hours_per_week", "full_time_required_hours"])
        self.env.cr.execute(SQL("SELECT id FROM resource_calendar WHERE %s", condition))
        return [("id", "in", [row[0] for row in self.env.cr.fetchall()])]

    # --------------------------------------------------
    # Overrides
    # --------------------------------------------------

    def copy_data(self, default: ValuesType | None = None) -> list[ValuesType]:
        vals_list = super().copy_data(default=default)
        return [
            dict(vals, name=self.env._("%s (copy)", calendar.name))
            for calendar, vals in zip(self, vals_list, strict=True)
        ]

    # --------------------------------------------------
    # Actions
    # --------------------------------------------------

    def switch_calendar_type(self):
        self.ensure_one()
        if not self.two_weeks_calendar:
            self.two_weeks_calendar = True
            final_attendances = self._get_two_weeks_attendance()
            self.attendance_ids = [Command.clear()] + final_attendances

        else:
            self.two_weeks_calendar = False
            self.attendance_ids.unlink()
            self.duration_based = False
            self.attendance_ids = self._get_default_attendance_ids(self.company_id)

    def switch_based_on_duration(self):
        self.ensure_one()
        self.duration_based = not self.duration_based
        if self.duration_based:
            self.attendance_ids.filtered(lambda att: att.day_period == "lunch").unlink()
        else:
            self.attendance_ids.unlink()
            default_vals = self._get_default_attendance_vals(self.company_id)
            if self.two_weeks_calendar:
                # Build the two-week set straight from the defaults.  Creating
                # the defaults first and then calling
                # ``_get_two_weeks_attendance()`` appended the duplicates next
                # to the originals — nothing cleared them — so the calendar
                # ended up with both, its week-less originals inflating
                # ``hours_per_week`` and belonging to neither week.
                self.attendance_ids = self._get_two_weeks_attendance(default_vals)
            else:
                self.attendance_ids = [Command.create(vals) for vals in default_vals]

    # --------------------------------------------------
    # Computation API
    # --------------------------------------------------

    def _prepare_dummy_attendance(self, hours, days):
        """Build a transient (unsaved) attendance carrying only a duration.

        Flexible / fully-flexible resources have no stored attendance lines, so
        the interval payload is a throwaway ``resource.calendar.attendance``
        record whose ``duration_hours`` / ``duration_days`` let downstream
        day-count helpers (``_get_attendance_intervals_days_data``) work
        unchanged.
        """
        return self.env["resource.calendar.attendance"].new(
            {"duration_hours": hours, "duration_days": days}
        )

    def _fully_flexible_attendance_intervals(self, start_datetime, end_datetime, tz):
        """Availability of a resource with no calendar at all: every day, in full.

        One interval **per calendar day** rather than a single block spanning the
        whole window.  The union is identical, so availability is unchanged --
        a fully flexible resource is still free at any instant of the range, and
        planning/gantt see exactly what they saw before.  What changes is how the
        range *measures*.

        ``_get_attendance_intervals_days_data`` reads a day count off the payload
        as ``duration_days x interval_hours / duration_hours``.  With one
        whole-window block carrying ``duration_days = hours / 24`` that ratio
        collapsed to "elapsed hours over 24", i.e. it counted **wall-clock**
        days: a Monday-to-Friday absence beginning at 08:00 and ending at 17:00
        measured 4.375 days instead of 5, and the shortfall grew with every
        boundary that was not midnight.

        Here each covered day carries a ``duration_days`` measured against an
        *expected working day* rather than against 24 hours, and capped at one:
        cover a day from 08:00 to midnight and it is one day, not 0.67; cover
        three hours of it and it is 3/8 of a day, not 3/24.  The reference is
        this calendar's ``hours_per_day`` when it has one, falling back to
        :data:`HOURS_PER_DAY` -- the module's own constant for exactly this
        "no calendar says otherwise" case, which nothing here used before.

        .. note::
           The *hours* figure is deliberately left as elapsed time, so a
           five-day absence still reports 105 hours rather than 40.  Fixing
           that means shortening the intervals themselves -- one noon-centred
           block per day, as ``_flexible_attendance_intervals`` already does --
           and the intervals are what every availability consumer reads, not
           just the measuring ones.

           The evidence, should someone pick this up: instrumenting this branch
           across ``hr``, ``hr_holidays``, ``mrp``, ``project`` and
           ``test_resource`` showed exactly one production entry point,
           ``hr_leave._get_durations`` via ``_list_work_time_per_day``, which
           only measures.  But ``enterprise`` holds ~20 further call sites of
           ``_work_intervals_batch`` / ``_attendance_intervals_batch``, among
           them ``planning``, ``project_enterprise``, ``appointment_hr`` and
           ``hr_attendance_gantt`` -- all of which decide *availability*, and
           none of which that instrumentation covered.  Shortening the blocks
           without auditing those risks making a fully flexible person
           unbookable outside 08:00-16:00, which is precisely what "fully
           flexible" denies.  The day count is the figure leave balances are
           kept in, and it is now right; the hours question needs that audit
           first.
        """
        self.ensure_one()
        expected_day_hours = self.hours_per_day or HOURS_PER_DAY
        intervals = []
        day = start_datetime.date()
        # The last microsecond of the range still belongs to the final day.
        last_day = (end_datetime - timedelta(microseconds=1)).date()
        while day <= last_day:
            # Localize each midnight separately rather than adding a timedelta to
            # an aware datetime: on a DST boundary the day is 23 or 25 hours long
            # and the shortcut would silently keep the old offset.
            midnight = datetime.combine(day, time.min).replace(tzinfo=tz)
            next_midnight = datetime.combine(day + timedelta(days=1), time.min).replace(
                tzinfo=tz
            )
            day_start = max(start_datetime, midnight)
            day_end = min(end_datetime, next_midnight)
            if day_end > day_start:
                covered_hours = (day_end - day_start).total_seconds() / 3600
                intervals.append(
                    (
                        day_start,
                        day_end,
                        self._prepare_dummy_attendance(
                            covered_hours,
                            min(1.0, covered_hours / expected_day_hours),
                        ),
                    )
                )
            day += timedelta(days=1)
        return intervals

    @staticmethod
    def _center_block_on_noon(day, hours, tz, lower, upper):
        """Center a ``hours``-long block on 12:00 of ``day``, tz-localized.

        The block is shifted (not shrunk) to stay within ``[lower, upper]`` —
        the queried window clipped to the day — so short days at the edges of
        the range keep their full allotted duration.
        """
        midpoint = datetime.combine(day, time(12, 0)).replace(tzinfo=tz)
        start_time = midpoint - timedelta(hours=hours / 2)
        end_time = midpoint + timedelta(hours=hours / 2)
        if start_time < lower:
            start_time = lower
            end_time = start_time + timedelta(hours=hours)
        elif end_time > upper:
            end_time = upper
            start_time = end_time - timedelta(hours=hours)
        return start_time, end_time

    def _get_flexible_hours_per_week(self):
        """Weekly working-hours budget for a flexible calendar.

        Flexible calendars have no fixed attendances, so ``_compute_hours_per_week``
        skips them and ``hours_per_week`` stays 0 unless a user sets it
        explicitly.  The effective weekly budget is therefore that explicit
        value when present, otherwise the full-time equivalent.  This is the
        single source of truth for every flexible-hours consumer (interval
        synthesis here, work-hours capping in ``resource.resource``).
        """
        self.ensure_one()
        return self.hours_per_week or self.full_time_required_hours

    def _flexible_attendance_intervals(self, start_datetime, end_datetime, tz):
        """Approximate a flexible calendar's work intervals over a window.

        Flexible calendars have no fixed attendance lines, so we synthesize
        them: fill each 7-day chunk up to the flexible weekly budget and each
        day up to ``hours_per_day``, centering each day's block on noon.  Each
        interval carries a throwaway attendance holding only its duration (see
        :meth:`_prepare_dummy_attendance`).

        .. important::
           The chunks are anchored on ``start_datetime``, not on the calendar
           week, and the fill is greedy from there.  That is deliberate: a
           flexible worker asked about Tue→Sat is credited five working days,
           not "whatever is left of the Monday-anchored week" — see
           ``hr_holidays`` ``test_undefined_working_hours``.

           The trade-off is that the result is **not additive**: asking about
           Mon→Mon returns one week's budget, while asking Mon→Thu and Thu→Mon
           separately and adding them returns more, because each sub-window
           starts a fresh budget.  Callers that partition a period and sum the
           parts (as two adjacent reservations covering one week do) will
           over-count.  Anchoring on the calendar week would fix that but would
           silently shorten every mid-week leave, so the semantics are left as
           they are and the limitation is documented here instead.
        """
        self.ensure_one()
        max_hours_per_week = self._get_flexible_hours_per_week()
        max_hours_per_day = self.hours_per_day
        first_day = start_datetime.date()
        # The last microsecond of the range still belongs to the final day.
        last_day = (end_datetime - timedelta(microseconds=1)).date()
        # Total span duration is timezone-independent (same instants).
        total_hours = (end_datetime - start_datetime).total_seconds() / 3600

        intervals = []
        # Iterate over plain dates.  Stepping an *aware* datetime by timedelta
        # keeps the old UTC offset across a DST switch, so the wall-clock day a
        # block is attributed to could drift by an hour and land on the wrong
        # date; dates have no such hazard.
        chunk_start = first_day
        while chunk_start <= last_day:
            chunk_end = min(chunk_start + timedelta(days=6), last_day)
            remaining_hours = min(max_hours_per_week, total_hours)

            day = chunk_start
            while day <= chunk_end:
                if remaining_hours <= 0:
                    break
                day_start = datetime.combine(day, time.min).replace(tzinfo=tz)
                day_end = datetime.combine(day, time.max).replace(tzinfo=tz)
                day_period_start = max(start_datetime, day_start)
                day_period_end = min(end_datetime, day_end)
                allocate_hours = min(
                    max_hours_per_day,
                    remaining_hours,
                    (day_period_end - day_period_start).total_seconds() / 3600,
                )
                remaining_hours -= allocate_hours
                start_time, end_time = self._center_block_on_noon(
                    day,
                    allocate_hours,
                    tz,
                    day_period_start,
                    day_period_end,
                )
                intervals.append(
                    (
                        start_time,
                        end_time,
                        self._prepare_dummy_attendance(allocate_hours, 1),
                    )
                )
                day += timedelta(days=1)
            chunk_start += timedelta(days=7)
        return intervals

    def _attendance_intervals_batch(
        self,
        start_dt: datetime,
        end_dt: datetime,
        resources: ResourceResource | None = None,
        domain: list | None = None,
        tz: ZoneInfo | str | None = None,
        lunch: bool = False,
    ) -> dict[int | bool, Intervals]:
        if not (start_dt.tzinfo and end_dt.tzinfo):
            raise ValueError("start_dt and end_dt must be timezone-aware")
        if not self:
            # ``Expected singleton: resource.calendar()`` gave no hint that the
            # caller had simply lost its calendar.  A resource with no calendar
            # is fully flexible and its availability is modelled by the caller
            # (see ``_get_valid_work_intervals``), never by this method.
            raise ValueError(
                "_attendance_intervals_batch requires a calendar; a resource"
                " without one is fully flexible and has no attendance lines"
            )
        self.ensure_one()
        # The signature accepts a tz name as well as a tzinfo; normalise once so
        # the ``.astimezone(tz)`` / dict-keying below never sees a bare string
        # (which raises ``TypeError: tzinfo argument must be ...``).
        if isinstance(tz, str):
            tz = timezone(tz)
        if not resources:
            resources = self.env["resource.resource"]
            resources_list = [resources]
        else:
            resources_list = list(resources) + [self.env["resource.resource"]]

        if self.flexible_hours and lunch:
            return {
                resource.id: Intervals([], keep_distinct=True)
                for resource in resources_list
            }

        domain = Domain.AND(
            [
                Domain(domain or Domain.TRUE),
                Domain("calendar_id", "=", self.id),
                Domain("display_type", "=", False),
                Domain("day_period", "!=" if not lunch else "=", "lunch"),
            ]
        )

        attendances = self.env["resource.calendar.attendance"].search(domain)
        # Since we only have one calendar to take in account
        # Group resources per tz they will all have the same result
        resources_per_tz = defaultdict(list)
        for resource in resources_list:
            resources_per_tz[tz or timezone((resource or self).tz)].append(resource)
        # Resource specific attendances
        # Calendar attendances per day of the week
        # * 7 days per week * 2 for two week calendars
        attendances_per_day = [
            self.env["resource.calendar.attendance"] for _ in range(14)
        ]
        weekdays = set()
        for attendance in attendances:
            weekday = int(attendance.dayofweek)
            weekdays.add(weekday)
            if self.two_weeks_calendar:
                weektype = int(attendance.week_type)
                attendances_per_day[weekday + 7 * weektype] |= attendance
            else:
                attendances_per_day[weekday] |= attendance
                attendances_per_day[weekday + 7] |= attendance

        start = start_dt.astimezone(UTC)
        end = end_dt.astimezone(UTC)
        bounds_per_tz = {
            tz: (start_dt.astimezone(tz), end_dt.astimezone(tz))
            for tz in resources_per_tz
        }
        # Use the outer bounds from the requested timezones
        for low, high in bounds_per_tz.values():
            start = min(start, low.replace(tzinfo=UTC))
            end = max(end, high.replace(tzinfo=UTC))
        # Generate once with utc as timezone
        days = rrule(DAILY, start.date(), until=end.date(), byweekday=weekdays)
        ResourceCalendarAttendance = self.env["resource.calendar.attendance"]
        base_result = []
        for day in days:
            week_type = ResourceCalendarAttendance.get_week_type(day)
            attendances = attendances_per_day[day.weekday() + 7 * week_type]
            for attendance in attendances:
                day_from = datetime.combine(day, float_to_time(attendance.hour_from))
                day_to = datetime.combine(day, float_to_time(attendance.hour_to))
                base_result.append((day_from, day_to, attendance))

        # Copy the result localized once per necessary timezone
        # Strictly speaking comparing start_dt < time or start_dt.astimezone(tz) < time
        # should always yield the same result. however while working with dates it is easier
        # if all dates have the same format
        result_per_tz = {
            tz: [
                (
                    max(bounds_per_tz[tz][0], val[0].replace(tzinfo=tz)),
                    min(bounds_per_tz[tz][1], val[1].replace(tzinfo=tz)),
                    val[2],
                )
                for val in base_result
            ]
            for tz in resources_per_tz
        }
        resource_calendars = resources._get_calendar_at(start_dt, tz)
        result_per_resource_id = {}
        for tz, tz_resources in resources_per_tz.items():
            res = result_per_tz[tz]

            res_intervals = Intervals(res, keep_distinct=True)
            start_datetime = start_dt.astimezone(tz)
            end_datetime = end_dt.astimezone(tz)

            for resource in tz_resources:
                if resource and not resource_calendars.get(resource, False):
                    # Fully flexible: available for the whole period, expressed one
                    # calendar day at a time so the range measures in days rather
                    # than in wall-clock hours (see the method's docstring).
                    result_per_resource_id[resource.id] = Intervals(
                        self._fully_flexible_attendance_intervals(
                            start_datetime, end_datetime, tz
                        ),
                        keep_distinct=True,
                    )
                elif self.flexible_hours or (
                    resource and resource_calendars[resource].flexible_hours
                ):
                    calendar = resource_calendars[resource] if resource else self
                    intervals = calendar._flexible_attendance_intervals(
                        start_datetime, end_datetime, tz
                    )
                    result_per_resource_id[resource.id] = Intervals(
                        intervals, keep_distinct=True
                    )
                else:
                    result_per_resource_id[resource.id] = res_intervals
        return result_per_resource_id

    def _handle_flexible_leave_interval(
        self, dt0: datetime, dt1: datetime, leave: Any
    ) -> tuple[datetime, datetime]:
        """Hook method to handle flexible leave intervals. Can be overridden in other modules."""
        tz = dt0.tzinfo  # Get the timezone information from dt0
        dt0 = datetime.combine(dt0.date(), time.min).replace(tzinfo=tz)
        dt1 = datetime.combine(dt1.date(), time.max).replace(tzinfo=tz)
        return dt0, dt1

    def _leave_intervals(
        self,
        start_dt: datetime,
        end_dt: datetime,
        resource: ResourceResource | None = None,
        domain: list | None = None,
        tz: ZoneInfo | str | None = None,
    ) -> Intervals:
        if resource is None:
            resource = self.env["resource.resource"]
        return self._leave_intervals_batch(
            start_dt,
            end_dt,
            resources=resource,
            domain=domain,
            tz=tz,
        )[resource.id]

    def _leave_intervals_batch(
        self,
        start_dt: datetime,
        end_dt: datetime,
        resources: ResourceResource | None = None,
        domain: list | None = None,
        tz: ZoneInfo | str | None = None,
    ) -> dict[int | bool, Intervals]:
        """Return the leave intervals in the given datetime range.
        The returned intervals are expressed in specified tz or in the calendar's timezone.
        """
        if not (start_dt.tzinfo and end_dt.tzinfo):
            raise ValueError("start_dt and end_dt must be timezone-aware")

        # Accept a tz name as well as a tzinfo (see _attendance_intervals_batch).
        if isinstance(tz, str):
            tz = timezone(tz)

        if domain is None:
            domain = [("time_type", "=", "leave")]

        resources_list = list(resources) if resources else []

        # The calendar-level key is always published, empty calendar included:
        # ``_leave_intervals`` reads ``result[False]`` unconditionally and used
        # to fail there with a bare ``KeyError: False``.
        resources_list.append(self.env["resource.resource"])
        # Rebuilt by unpacking, never with ``+=``: ``domain`` is the caller's
        # own list and an in-place extend would leave our leave filters in it.
        calendar_leaf = (
            ("calendar_id", "in", [False] + self.ids)
            if self
            # No calendar means no calendar-bound leaves.  Without this branch
            # the domain carried no calendar filter at all, so an empty
            # recordset swept *every* leave in the database and attributed them
            # to the queried resources.
            else ("calendar_id", "=", False)
        )
        # for the computation, express all datetimes in UTC
        # Public leave don't have a resource_id
        domain = [
            *domain,
            calendar_leaf,
            ("resource_id", "in", [False] + [r.id for r in resources_list]),
            ("date_from", "<=", end_dt.astimezone(UTC).replace(tzinfo=None)),
            ("date_to", ">=", start_dt.astimezone(UTC).replace(tzinfo=None)),
        ]

        # Resolve each queried resource's timezone and localized window once —
        # the reconciliation below is O(leaves × resources) and previously
        # redid these conversions per (leave, resource) pair.
        window_per_resource = [
            (
                resource,
                resource_tz := tz or timezone((resource or self).tz or "UTC"),
                start_dt.astimezone(resource_tz),
                end_dt.astimezone(resource_tz),
            )
            for resource in resources_list
        ]

        # retrieve leave intervals in (start_dt, end_dt)
        result = defaultdict(list)
        leave_bounds = {}  # (leave.id, tz) → (dt0, dt1), shared across resources
        all_leaves = self.env["resource.calendar.leaves"].search(domain)
        for leave in all_leaves:
            leave_resource = leave.resource_id
            leave_company = leave.company_id
            leave_date_from = leave.date_from
            leave_date_to = leave.date_to
            for resource, resource_tz, start, end in window_per_resource:
                if leave_resource.id not in [False, resource.id]:
                    # A leave bound to another resource.
                    continue
                if (
                    not leave_resource
                    and resource
                    and leave_company
                    and resource.company_id
                    and resource.company_id != leave_company
                ):
                    # A *global* leave belongs to the company that declared it,
                    # so it does not reach another company's resources.  Both
                    # sides must actually name a company for that to be a
                    # mismatch, though: an empty company is "not scoped", not
                    # "scoped to nobody".  Comparing it as a value meant a
                    # company-less resource -- or a holiday declared without
                    # one -- observed no public holiday at all, while the
                    # multi-company record rule on this very model admits
                    # ``company_id = False`` for exactly the opposite reason.
                    continue
                bounds_key = (leave.id, resource_tz)
                if bounds_key in leave_bounds:
                    dt0, dt1 = leave_bounds[bounds_key]
                else:
                    dt0 = leave_date_from.astimezone(resource_tz)
                    dt1 = leave_date_to.astimezone(resource_tz)
                    if leave_resource and leave_resource._is_flexible():
                        dt0, dt1 = self._handle_flexible_leave_interval(dt0, dt1, leave)
                    leave_bounds[bounds_key] = (dt0, dt1)
                result[resource.id].append((max(start, dt0), min(end, dt1), leave))

        return {r.id: Intervals(result[r.id]) for r in resources_list}

    def _work_intervals_batch(
        self,
        start_dt: datetime,
        end_dt: datetime,
        resources: ResourceResource | None = None,
        domain: list | None = None,
        tz: ZoneInfo | str | None = None,
        compute_leaves: bool = True,
    ) -> dict[int | bool, Intervals]:
        """Return the effective work intervals between the given datetimes."""
        if not resources:
            resources = self.env["resource.resource"]
            resources_list = [resources]
        else:
            resources_list = list(resources) + [self.env["resource.resource"]]

        # Resolve the effective timezone ONCE and hand the same one to both
        # halves.  Previously only the attendance half honoured the
        # ``employee_timezone`` context key, so with that key set the two sides
        # of the subtraction were built on different day boundaries — which
        # matters because ``_leave_intervals_batch`` expands a flexible
        # resource's leave to whole *local* days.
        effective_tz = tz or self.env.context.get("employee_timezone")
        attendance_intervals = self._attendance_intervals_batch(
            start_dt,
            end_dt,
            resources,
            tz=effective_tz,
        )
        if compute_leaves:
            leave_intervals = self._leave_intervals_batch(
                start_dt, end_dt, resources, domain, tz=effective_tz
            )
            return {
                r.id: (attendance_intervals[r.id] - leave_intervals[r.id])
                for r in resources_list
            }
        return {r.id: attendance_intervals[r.id] for r in resources_list}

    def _unavailable_intervals(
        self,
        start_dt: datetime,
        end_dt: datetime,
        resource: ResourceResource | None = None,
        domain: list | None = None,
        tz: ZoneInfo | str | None = None,
    ) -> list[tuple[datetime, datetime]]:
        if resource is None:
            resource = self.env["resource.resource"]
        return self._unavailable_intervals_batch(
            start_dt,
            end_dt,
            resources=resource,
            domain=domain,
            tz=tz,
        )[resource.id]

    def _unavailable_intervals_batch(
        self,
        start_dt: datetime,
        end_dt: datetime,
        resources: ResourceResource | None = None,
        domain: list | None = None,
        tz: ZoneInfo | str | None = None,
    ) -> dict[int | bool, list[tuple[datetime, datetime]]]:
        """Return the unavailable intervals between the given datetimes."""
        if not resources:
            resources = self.env["resource.resource"]
            resources_list = [resources]
        else:
            resources_list = list(resources)

        resources_work_intervals = self._work_intervals_batch(
            start_dt, end_dt, resources, domain, tz
        )
        result = {}
        for resource in resources_list:
            if resource and resource._is_flexible():
                leaves = self._leave_intervals_batch(
                    start_dt, end_dt, resource, domain, tz=tz
                )
                # Always publish a key, even with no leaves.  Skipping the
                # assignment left the resource absent from the returned dict:
                # ``_unavailable_intervals`` then raised KeyError, and the
                # gantt consumers that read this through
                # ``.get(resource.id, company_leaves)`` silently fell back to
                # the *company* calendar's unavailability — greying out cells
                # for a flexible resource that is in fact available.
                result[resource.id] = [
                    (i[0].astimezone(UTC), i[1].astimezone(UTC))
                    for i in leaves.get(resource.id, [])
                ]
                continue
            work_intervals = [
                (start, stop)
                for start, stop, meta in resources_work_intervals[resource.id]
            ]
            work_intervals = (
                [start_dt] + list(chain.from_iterable(work_intervals)) + [end_dt]
            )
            # put it back to UTC
            work_intervals = [dt.astimezone(UTC) for dt in work_intervals]
            # pick groups of two
            work_intervals = list(
                zip(work_intervals[0::2], work_intervals[1::2], strict=True)
            )
            result[resource.id] = work_intervals
        return result

    # --------------------------------------------------
    # Private Methods / Helpers
    # --------------------------------------------------

    def _check_overlap(self, attendance_ids: ResourceCalendarAttendance) -> None:
        """attendance_ids correspond to attendance of a week,
        will check for each day of week that there are no superimpose."""
        # Zero-length lines are excluded first: they cover no time, so they cannot
        # overlap anything.  The nudge below would invert them (start > stop),
        # ``Intervals`` drops an inverted tuple, and the length comparison then
        # reported an "overlap" for a calendar holding a single 0-hour day.  That
        # is reachable: on a duration-based calendar ``_inverse_duration_hours``
        # turns ``duration_hours = 0`` into ``hour_from == hour_to == 12``.
        timed_attendances = [
            attendance
            for attendance in attendance_ids
            if attendance.hour_to > attendance.hour_from
        ]
        # 0.000001 is added to each start hour to avoid detecting two contiguous intervals as superimposing.
        # Indeed Intervals function will join 2 intervals with the start and stop hour corresponding.
        result = [
            (
                int(attendance.dayofweek) * 24 + attendance.hour_from + 0.000001,
                int(attendance.dayofweek) * 24 + attendance.hour_to,
                attendance,
            )
            for attendance in timed_attendances
        ]

        if len(Intervals(result)) != len(result):
            raise ValidationError(self.env._("Attendances can't overlap."))

    def _get_attendance_intervals_days_data(
        self, attendance_intervals: Intervals
    ) -> dict[str, float]:
        """
        helper function to compute duration of `intervals` that have
        'resource.calendar.attendance' records as payload (3rd element in tuple).
        expressed in days and hours.

        resource.calendar.attendance records have durations associated
        with them so this method merely calculates the proportion that is
        covered by the intervals.
        """
        day_hours = defaultdict(float)
        day_days = defaultdict(float)
        for start, stop, meta in attendance_intervals:
            # If the interval covers only a part of the original attendance, we
            # take durations in days proportionally to what is left of the interval.
            interval_hours = (stop - start).total_seconds() / 3600
            day_hours[start.date()] += interval_hours
            if len(self) == 1 and self.flexible_hours:
                day_days[start.date()] += (
                    interval_hours / self.hours_per_day if self.hours_per_day else 0
                )
            else:
                total_duration_hours = sum(meta.mapped("duration_hours"))
                if total_duration_hours:
                    day_days[start.date()] += (
                        sum(meta.mapped("duration_days"))
                        * interval_hours
                        / total_duration_hours
                    )

        return {
            # Round the day count to the nearest thousandth of a day, which is
            # fine enough for half/quarter-day attendances while absorbing the
            # float noise of the proportional split above.
            "days": float_round(sum(day_days.values()), precision_rounding=0.001),
            "hours": sum(day_hours.values()),
        }

    def _get_closest_work_time(
        self,
        dt: datetime,
        match_end: bool = False,
        resource: ResourceResource | None = None,
        search_range: list[datetime] | None = None,
        compute_leaves: bool = True,
    ) -> datetime | None:
        """Return the closest work interval boundary within the search range.
        Consider only starts of intervals unless `match_end` is True. It will then only consider
        ends of intervals.
        :param dt: reference datetime
        :param match_end: wether to search for the begining of an interval or the end.
        :param search_range: time interval considered. Defaults to the entire day of `dt`
        :rtype: datetime | None
        """

        def interval_dt(interval):
            return interval[1 if match_end else 0]

        tz = resource.tz if resource else self.tz
        if resource is None:
            resource = self.env["resource.resource"]

        if not dt.tzinfo or (
            search_range and not (search_range[0].tzinfo and search_range[1].tzinfo)
        ):
            raise ValueError(self.env._("Provided datetimes needs to be timezoned"))

        dt = dt.astimezone(timezone(tz))

        if not search_range:
            range_start = dt + relativedelta(hour=0, minute=0, second=0)
            range_end = dt + relativedelta(days=1, hour=0, minute=0, second=0)
        else:
            range_start, range_end = search_range

        if not range_start <= dt <= range_end:
            return None
        work_intervals = sorted(
            self._work_intervals_batch(
                range_start, range_end, resource, compute_leaves=compute_leaves
            )[resource.id],
            key=lambda i: abs(interval_dt(i) - dt),
        )
        return interval_dt(work_intervals[0]) if work_intervals else None

    def _get_days_per_week(self) -> float:
        # If the employee didn't work a full day, it is still counted, i.e. 19h / week (M/T/W(half day)) -> 3 days
        self.ensure_one()
        attendances = self._get_global_attendances()
        if self.two_weeks_calendar:
            number_of_days = len(
                set(
                    attendances.filtered(lambda cal: cal.week_type == "1").mapped(
                        "dayofweek"
                    )
                )
            )
            number_of_days += len(
                set(
                    attendances.filtered(lambda cal: cal.week_type == "0").mapped(
                        "dayofweek"
                    )
                )
            )
        else:
            number_of_days = len(set(attendances.mapped("dayofweek")))
        return number_of_days / 2 if self.two_weeks_calendar else number_of_days

    def _get_hours_per_week(self) -> float:
        """Calculate the average hours worked per week."""
        self.ensure_one()
        hour_count = 0.0
        for attendance in self._get_global_attendances():
            if self.duration_based:
                hour_count += attendance.duration_hours
            else:
                hour_count += attendance.hour_to - attendance.hour_from
        return hour_count / 2 if self.two_weeks_calendar else hour_count

    def _get_hours_per_day(self) -> float:
        """Calculate the average hours worked per workday."""
        hour_per_week = self._get_hours_per_week()
        number_of_days = self._get_days_per_week()
        return hour_per_week / number_of_days if number_of_days else 0

    def _get_global_attendances(self):
        return self.attendance_ids.filtered(
            lambda attendance: (
                attendance.day_period != "lunch" and not attendance.display_type
            )
        )

    def _get_unusual_days(self, start_dt, end_dt, company_id=False):
        if not self:
            return {}
        self.ensure_one()
        if not start_dt.tzinfo:
            start_dt = start_dt.replace(tzinfo=UTC)
        if not end_dt.tzinfo:
            end_dt = end_dt.replace(tzinfo=UTC)

        domain = []
        if company_id:
            domain = [("company_id", "in", (company_id.id, False))]
        if self.flexible_hours:
            leave_intervals = self._leave_intervals_batch(
                start_dt, end_dt, domain=domain
            )[False]
            works = set()
            for start_int, end_int, _ in leave_intervals:
                works.update(
                    start_int.date() + timedelta(days=i)
                    for i in range((end_int.date() - start_int.date()).days + 1)
                )
            return {
                fields.Date.to_string(day.date()): (day.date() in works)
                for day in rrule(DAILY, start_dt, until=end_dt)
            }
        works = {
            d[0].date()
            for d in self._work_intervals_batch(start_dt, end_dt, domain=domain)[False]
        }
        return {
            fields.Date.to_string(day.date()): (day.date() not in works)
            for day in rrule(DAILY, start_dt, until=end_dt)
        }

    def _get_default_attendance_ids(self, company_id=None):
        """Same as :meth:`_get_default_attendance_vals`, as x2many commands."""
        return [
            Command.create(vals)
            for vals in self._get_default_attendance_vals(company_id)
        ]

    def _get_default_attendance_vals(self, company_id=None):
        """Return a copy of the company's calendar attendance, or the default
        40 hours/week, as plain dicts.

        Kept separate from the command form so callers that need to transform
        the lines before creating them — ``switch_based_on_duration`` has to
        spread them over two weeks — can do so without a round trip through
        the database.
        """
        if company_id and (
            attendances := company_id.resource_calendar_id.attendance_ids
        ):
            return [
                {
                    "name": attendance.name,
                    "dayofweek": attendance.dayofweek,
                    "week_type": attendance.week_type,
                    "hour_from": attendance.hour_from,
                    "hour_to": attendance.hour_to,
                    "day_period": attendance.day_period,
                    "display_type": attendance.display_type,
                }
                for attendance in attendances
            ]
        # Standard Mon-Fri 8-12 / 12-13 (lunch) / 13-17.  The full per-day
        # names are kept verbatim as translation keys so existing ``.po``
        # entries keep matching.
        default_days = (
            (
                "0",
                self.env._("Monday Morning"),
                self.env._("Monday Lunch"),
                self.env._("Monday Afternoon"),
            ),
            (
                "1",
                self.env._("Tuesday Morning"),
                self.env._("Tuesday Lunch"),
                self.env._("Tuesday Afternoon"),
            ),
            (
                "2",
                self.env._("Wednesday Morning"),
                self.env._("Wednesday Lunch"),
                self.env._("Wednesday Afternoon"),
            ),
            (
                "3",
                self.env._("Thursday Morning"),
                self.env._("Thursday Lunch"),
                self.env._("Thursday Afternoon"),
            ),
            (
                "4",
                self.env._("Friday Morning"),
                self.env._("Friday Lunch"),
                self.env._("Friday Afternoon"),
            ),
        )
        periods = (("morning", 8, 12), ("lunch", 12, 13), ("afternoon", 13, 17))
        return [
            {
                "name": name,
                "dayofweek": dayofweek,
                "hour_from": hour_from,
                "hour_to": hour_to,
                "day_period": day_period,
            }
            for dayofweek, *names in default_days
            for (day_period, hour_from, hour_to), name in zip(
                periods, names, strict=True
            )
        ]

    def _get_two_weeks_attendance(self, attendance_vals=None):
        """Spread ``attendance_vals`` over two week-typed sets, with sections.

        ``attendance_vals`` defaults to this calendar's own lines, which is what
        ``switch_calendar_type`` needs.  Callers that are *replacing* the lines
        pass the replacements directly: materialising them first and reading
        them back would leave the calendar holding week-less lines, which a
        two-weeks calendar must never have.
        """
        if attendance_vals is None:
            attendance_vals = [
                attendance._copy_attendance_vals() for attendance in self.attendance_ids
            ]
        # The second-week section must sort after every first-week line
        # whatever the calendar size (the old fixed offset of 25 let week-one
        # lines of a 25+-line calendar spill past the section marker, which
        # ``_onchange_attendance_ids`` then reassigned to the wrong week).
        second_week_seq = len(attendance_vals) + 1
        final_attendances = [
            Command.create(
                {
                    "name": "First week",
                    "dayofweek": "0",
                    "sequence": 0,
                    "hour_from": 0,
                    "day_period": "morning",
                    "week_type": "0",
                    "hour_to": 0,
                    "display_type": "line_section",
                }
            ),
            Command.create(
                {
                    "name": "Second week",
                    "dayofweek": "0",
                    "sequence": second_week_seq,
                    "hour_from": 0,
                    "day_period": "morning",
                    "week_type": "1",
                    "hour_to": 0,
                    "display_type": "line_section",
                }
            ),
        ]
        for idx, vals in enumerate(attendance_vals):
            final_attendances.append(
                Command.create(dict(vals, week_type="0", sequence=idx + 1))
            )
            final_attendances.append(
                Command.create(
                    dict(vals, week_type="1", sequence=second_week_seq + idx + 1)
                )
            )
        return final_attendances

    # --------------------------------------------------
    # External API
    # --------------------------------------------------

    def get_work_hours_count(
        self,
        start_dt: datetime,
        end_dt: datetime,
        compute_leaves: bool = True,
        domain: list | None = None,
    ) -> float:
        """
        `compute_leaves` controls whether or not this method is taking into
        account the global leaves.

        `domain` controls the way leaves are recognized.
        None means default value ('time_type', '=', 'leave')

        Counts the number of work hours between two datetimes.
        """
        self.ensure_one()
        # Set timezone in UTC if no timezone is explicitly given
        if not start_dt.tzinfo:
            start_dt = start_dt.replace(tzinfo=UTC)
        if not end_dt.tzinfo:
            end_dt = end_dt.replace(tzinfo=UTC)

        if compute_leaves:
            intervals = self._work_intervals_batch(start_dt, end_dt, domain=domain)[
                False
            ]
        else:
            intervals = self._attendance_intervals_batch(start_dt, end_dt)[False]

        return sum(
            (stop - start).total_seconds() / 3600 for start, stop, meta in intervals
        )

    def get_work_duration_data(
        self,
        from_datetime: datetime,
        to_datetime: datetime,
        compute_leaves: bool = True,
        domain: list | None = None,
    ) -> dict[str, float]:
        """
        Get the working duration (in days and hours) for a given period, only
        based on the current calendar. This method does not use resource to
        compute it.

        `domain` is used in order to recognise the leaves to take,
        None means default value ('time_type', '=', 'leave')

        Returns a dict {'days': n, 'hours': h} containing the
        quantity of working time expressed as days and as hours.
        """
        # naive datetimes are made explicit in UTC
        from_datetime = localized(from_datetime)
        to_datetime = localized(to_datetime)

        # actual hours per day
        if compute_leaves:
            intervals = self._work_intervals_batch(
                from_datetime, to_datetime, domain=domain
            )[False]
        else:
            intervals = self._attendance_intervals_batch(
                from_datetime, to_datetime, domain=domain
            )[False]

        return self._get_attendance_intervals_days_data(intervals)

    def plan_hours(
        self,
        hours: float,
        day_dt: datetime,
        compute_leaves: bool = False,
        domain: list | None = None,
        resource: ResourceResource | None = None,
    ) -> datetime | bool:
        """
        `compute_leaves` controls whether or not this method is taking into
        account the global leaves.

        `domain` controls the way leaves are recognized.
        None means default value ('time_type', '=', 'leave')

        Return datetime after having planned hours
        """
        revert = to_timezone(day_dt.tzinfo)
        day_dt = localized(day_dt)

        if resource is None:
            resource = self.env["resource.resource"]

        # NB: ``hours = 0`` deliberately falls through to the scan below and
        # answers with the start of the next work interval, not with ``day_dt``.
        # That is the continuous reading -- ``plan_hours(0.0002)`` lands at
        # 08:00:00.72 of the same interval, so zero landing at 08:00 is its
        # limit, and both skip a day the resource is on leave.  It differs from
        # ``resource.scheduling.tools._scheduling_plan_hours``, which short-
        # circuits zero to its input; that helper is asking "when does this
        # finish", while this one answers "when does the work start".
        # (``test_resource``'s ``test_plan_hours`` pins both branches.)

        # which method to use for retrieving intervals
        if compute_leaves:
            get_intervals = partial(
                self._work_intervals_batch, domain=domain, resources=resource
            )
            resource_id = resource.id
        else:
            get_intervals = self._attendance_intervals_batch
            resource_id = False

        if hours >= 0:
            delta = _PLAN_WINDOW
            for n in range(_PLAN_MAX_ITERATIONS):
                dt = day_dt + delta * n
                for start, stop, _meta in get_intervals(dt, dt + delta)[resource_id]:
                    interval_hours = (stop - start).total_seconds() / 3600
                    if hours <= interval_hours:
                        return revert(start + timedelta(hours=hours))
                    hours -= interval_hours
            return False
        hours = abs(hours)
        delta = _PLAN_WINDOW
        for n in range(_PLAN_MAX_ITERATIONS):
            dt = day_dt - delta * n
            for start, stop, _meta in reversed(
                get_intervals(dt - delta, dt)[resource_id]
            ):
                interval_hours = (stop - start).total_seconds() / 3600
                if hours <= interval_hours:
                    return revert(stop - timedelta(hours=hours))
                hours -= interval_hours
        return False

    def plan_days(
        self,
        days: int,
        day_dt: datetime,
        compute_leaves: bool = False,
        domain: list | None = None,
        resource: ResourceResource | None = None,
    ) -> datetime | bool:
        """
        `compute_leaves` controls whether or not this method is taking into
        account the global leaves.

        `domain` controls the way leaves are recognized.
        None means default value ('time_type', '=', 'leave')

        `resource` scopes the leaves to that resource, mirroring
        :meth:`plan_hours`.  Without it only *global* leaves were ever
        subtracted, so ``compute_leaves=True`` happily planned work onto days
        the resource was on leave.

        Returns the datetime of a days scheduling.
        """
        revert = to_timezone(day_dt.tzinfo)
        day_dt = localized(day_dt)

        if resource is None:
            resource = self.env["resource.resource"]

        # which method to use for retrieving intervals
        if compute_leaves:
            get_intervals = partial(
                self._work_intervals_batch, domain=domain, resources=resource
            )
            resource_id = resource.id
        else:
            get_intervals = self._attendance_intervals_batch
            resource_id = False

        # A working day is only complete once an interval belonging to the NEXT
        # day shows up: returning on the first interval of the n-th day handed
        # back the end of that day's first attendance block, i.e. lunchtime on
        # any calendar with a midday break (the Odoo default).  ``plan_hours``
        # already agreed with the end of the day; these two now match.
        if days > 0:
            found = set()
            boundary = None
            delta = _PLAN_WINDOW
            for n in range(_PLAN_MAX_ITERATIONS):
                dt = day_dt + delta * n
                for start, stop, _meta in get_intervals(dt, dt + delta)[resource_id]:
                    if start.date() not in found:
                        if len(found) == days:
                            return revert(boundary)
                        found.add(start.date())
                    boundary = stop
            return False

        if days < 0:
            days = abs(days)
            found = set()
            boundary = None
            delta = _PLAN_WINDOW
            for n in range(_PLAN_MAX_ITERATIONS):
                dt = day_dt - delta * n
                for start, _stop, _meta in reversed(
                    get_intervals(dt - delta, dt)[resource_id]
                ):
                    if start.date() not in found:
                        if len(found) == days:
                            return revert(boundary)
                        found.add(start.date())
                    boundary = start
            return False

        return revert(day_dt)

    def _works_on_date(self, date: date) -> bool:
        self.ensure_one()

        working_days = self._get_working_hours()
        dayofweek = str(date.weekday())
        if self.two_weeks_calendar:
            weektype = str(self.env["resource.calendar.attendance"].get_week_type(date))
            return working_days[weektype][dayofweek]
        return working_days[False][dayofweek]

    def _get_hours_for_date(
        self, target_date: date, day_period: str | None = None
    ) -> tuple[float, float]:
        """
        An instance method on a calendar to get the start and end float hours for a given date.

        .. important::
           When ``target_date`` falls on a day the calendar does not work, this
           does **not** return ``(0, 0)``: it falls back to the earliest
           ``hour_from`` and the latest ``hour_to`` found anywhere in the
           schedule.  That is deliberate — ``hr_holidays`` relies on it to give
           a leave request spanning a weekend a sensible span — but it means the
           result cannot be used to decide *whether* a day is worked.  Ask
           :meth:`_works_on_date` for that.

        :param target_date: The date to find working hours.
        :param day_period: Optional string ('morning', 'afternoon') to filter for half-days.
        :return: A tuple of floats (hour_from, hour_to).
        """
        self.ensure_one()
        if not target_date:
            err = "Target Date cannot be empty"
            raise ValueError(err)
        if self.flexible_hours:
            # Quick calculation to center flexible hours around 12PM midday
            datetimes = [
                12.0 - self.hours_per_day / 2.0,
                12.0,
                12.0 + self.hours_per_day / 2.0,
            ]
            if day_period:
                return (
                    (datetimes[0], datetimes[1])
                    if day_period == "morning"
                    else (datetimes[1], datetimes[2])
                )
            return (datetimes[0], datetimes[2])

        domain = [
            ("calendar_id", "=", self.id),
            ("display_type", "=", False),
            ("day_period", "!=", "lunch"),
        ]

        init_attendances = self.env["resource.calendar.attendance"]._read_group(
            domain=domain,
            groupby=["week_type", "dayofweek", "day_period"],
            aggregates=["hour_from:min", "hour_to:max"],
            order="dayofweek,hour_from:min",
        )

        init_attendances = [
            DummyAttendance(hour_from, hour_to, dayofweek, day_period, week_type)
            for week_type, dayofweek, day_period, hour_from, hour_to in init_attendances
        ]

        if day_period:
            attendances = [
                att for att in init_attendances if att.day_period == day_period
            ]
            attendances.extend(
                # Split full-day attendances at their midpoint.
                attendance._replace(
                    hour_from=(
                        attendance.hour_from
                        if day_period == "morning"
                        else (attendance.hour_from + attendance.hour_to) / 2
                    ),
                    hour_to=(
                        attendance.hour_to
                        if day_period == "afternoon"
                        else (attendance.hour_from + attendance.hour_to) / 2
                    ),
                )
                for attendance in init_attendances
                if attendance.day_period == "full_day"
            )

        else:
            attendances = init_attendances

        default_start = min((att.hour_from for att in attendances), default=0.0)
        default_end = max((att.hour_to for att in attendances), default=0.0)

        week_type = False
        if self.two_weeks_calendar:
            week_type = str(
                self.env["resource.calendar.attendance"].get_week_type(target_date)
            )

        filtered_attendances = [
            att
            for att in attendances
            if att.week_type == week_type
            and int(att.dayofweek) == target_date.weekday()
        ]
        hour_from = min(
            (att.hour_from for att in filtered_attendances), default=default_start
        )
        hour_to = max(
            (att.hour_to for att in filtered_attendances), default=default_end
        )

        return (hour_from, hour_to)

    def _get_working_hours(self):
        # NOT ormcached: the result is derived from ``attendance_ids``, and an
        # ``@ormcache('self.id')`` would never be invalidated when a calendar's
        # attendances change (nothing in this module clears ormcaches), so
        # ``_works_on_date`` and downstream leave/planning consumers would read
        # stale working days for the lifetime of the worker.  Rebuilding the
        # dict is O(#attendances) over already-prefetched records — negligible.
        self.ensure_one()

        working_days = defaultdict(lambda: defaultdict(lambda: False))
        # Only real work lines mark a day as worked: section rows are pure UX
        # (their ``dayofweek`` is always the default Monday, so counting them
        # flagged Monday as worked on every two-week calendar) and a lunch
        # break alone is not work time.
        for attendance in self._get_global_attendances():
            working_days[attendance.week_type][attendance.dayofweek] = True
        return working_days
