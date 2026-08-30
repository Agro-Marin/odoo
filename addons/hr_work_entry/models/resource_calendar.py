from odoo import api, models
from odoo.libs.intervals import Intervals


class ResourceCalendar(models.Model):
    _inherit = "resource.calendar"

    # Override the method to add 'attendance_ids.work_entry_type_id.is_leave' to the dependencies
    @api.depends("attendance_ids.work_entry_type_id.is_leave")
    def _compute_hours_per_week(self):
        super()._compute_hours_per_week()

    def _get_global_attendances(self):
        return (
            super()
            ._get_global_attendances()
            .filtered(lambda a: not a.work_entry_type_id.is_leave)
        )

    def _work_intervals_batch(
        self,
        start_dt,
        end_dt,
        resources=None,
        domain=None,
        tz=None,
        compute_leaves=True,
    ):
        """Drop the intervals of the schedule lines typed as time off.

        ``_get_global_attendances`` already excludes them, which is what makes
        ``hours_per_week`` read 32 on a calendar whose Friday is typed as
        unpaid. The interval side had never been told, so ``_get_unusual_days``
        went on painting that Friday as a working day and the same calendar
        answered two different things about the same week.

        The lines are filtered out of what ``super()`` returns rather than
        subtracted as a second interval set: a line typed as time off stops
        being work time, it does not carve a hole out of the lines beside it,
        which is the shape ``_get_global_attendances`` already has.
        """
        intervals_per_resource = super()._work_intervals_batch(
            start_dt,
            end_dt,
            resources=resources,
            domain=domain,
            tz=tz,
            compute_leaves=compute_leaves,
        )
        return {
            resource_id: Intervals(
                [
                    interval
                    for interval in intervals
                    # sudo: ``work_entry_type_id`` is behind hr.group_hr_user,
                    # and mrp, project and hr_calendar reach this method as
                    # ordinary users. A flexible resource carries a dummy
                    # attendance with no type at all, hence any() over a
                    # possibly empty mapping rather than a direct read.
                    if not any(interval[2].sudo().mapped("work_entry_type_id.is_leave"))
                ],
                keep_distinct=True,
            )
            for resource_id, intervals in intervals_per_resource.items()
        }

    def _get_default_attendance_vals(self, company_id=None):
        """Carry the company's per-line work entry type into the copy.

        ``resource`` builds these vals as a literal dict, and a field this
        module adds cannot be in it, so a schedule created from the company's
        came back with every line reset to ``_default_work_entry_type_id``.
        The copy the *onchange* path takes goes through
        ``_copy_attendance_vals``, which this module already extends, so the two
        ways of being born disagreed on which rule pays those hours.

        Only ``work_entry_type_id`` is added, rather than delegating the whole
        dict to ``_copy_attendance_vals``: that one also carries ``sequence``,
        and these vals feed ``_get_two_weeks_attendance``, where the week
        sections assign sequences of their own.
        """
        vals_list = super()._get_default_attendance_vals(company_id)
        attendances = (
            company_id.resource_calendar_id.attendance_ids
            if company_id
            else self.env["resource.calendar.attendance"]
        )
        if len(attendances) != len(vals_list):
            # No company calendar to copy: super() fell back to its own
            # 40 hours/week default, whose lines have no source to read a type
            # from and are left to the field default.
            return vals_list
        for vals, attendance in zip(vals_list, attendances, strict=True):
            vals["work_entry_type_id"] = attendance.work_entry_type_id.id
        return vals_list
