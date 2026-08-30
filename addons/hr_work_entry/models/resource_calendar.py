from odoo import api, models


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
