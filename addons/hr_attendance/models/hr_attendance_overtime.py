from odoo import api, fields, models


class HrAttendanceOvertimeLine(models.Model):
    _name = "hr.attendance.overtime.line"
    _description = "Attendance Overtime Line"
    _rec_name = "employee_id"
    _order = "time_start"

    employee_id = fields.Many2one(
        "hr.employee", string="Employee", required=True, ondelete="cascade", index=True
    )
    company_id = fields.Many2one(related="employee_id.company_id")

    date = fields.Date(string="Day", index=True, required=True)
    status = fields.Selection(
        [
            ("to_approve", "To Approve"),
            ("approved", "Approved"),
            ("refused", "Refused"),
        ],
        compute="_compute_status",
        required=True,
        store=True,
        readonly=False,
        precompute=True,
    )
    duration = fields.Float(string="Extra Hours", default=0.0, required=True)
    manual_duration = fields.Float(
        string="Extra Hours (encoded)",
        compute="_compute_manual_duration",
        store=True,
        readonly=False,
    )

    time_start = fields.Datetime(string="Start")
    time_stop = fields.Datetime(string="Stop")
    amount_rate = fields.Float("Overtime pay rate", required=True, default=1.0)

    is_manager = fields.Boolean(compute="_compute_is_manager")

    rule_ids = fields.Many2many("hr.attendance.overtime.rule", string="Applied Rules")

    _overtime_start_before_end = models.Constraint(
        "CHECK (time_stop > time_start)",
        "Starting time should be before end time.",
    )

    @api.depends("employee_id")
    def _compute_status(self):
        for overtime in self:
            if not overtime.status:
                overtime.status = (
                    "to_approve"
                    if overtime.employee_id.company_id.attendance_overtime_validation
                    == "by_manager"
                    else "approved"
                )

    @api.depends("duration")
    def _compute_manual_duration(self):
        for overtime in self:
            overtime.manual_duration = overtime.duration

    @api.depends("employee_id")
    def _compute_is_manager(self):
        has_manager_right = self.env.user.has_group(
            "hr_attendance.group_hr_attendance_manager"
        )
        has_officer_right = self.env.user.has_group(
            "hr_attendance.group_hr_attendance_officer"
        )
        for overtime in self:
            overtime.is_manager = has_manager_right or (
                has_officer_right
                and overtime.employee_id.attendance_manager_id == self.env.user
            )

    def action_approve(self):
        self.write({"status": "approved"})

    def action_refuse(self):
        self.write({"status": "refused"})

    def _linked_attendances(self):
        return self.env["hr.attendance"].search(
            [
                ("check_in", "in", self.mapped("time_start")),
                ("employee_id", "in", self.employee_id.ids),
            ]
        )

    # The attendance fields derived from these lines. `hr.attendance` declares
    # them `@api.depends("check_in", "check_out", "employee_id")`, which is not
    # where their value comes from: it comes from the lines below, reached
    # through a non-stored computed many2many the ORM cannot traverse backwards.
    # So the dependency is hand-rolled here, and it has to name every one of
    # them -- `overtime_hours` was missing, which left an attendance reporting
    # `validated_overtime_hours` and `overtime_hours` that contradicted each
    # other after any correction to the encoded hours.
    # `expected_hours` is `worked_hours - overtime_hours`. Marking a stored
    # field through `add_to_compute` does not cascade to the fields that depend
    # on it, so anything downstream has to be named here too.
    _ATTENDANCE_DERIVED_FIELDS = (
        "overtime_hours",
        "validated_overtime_hours",
        "overtime_status",
        "expected_hours",
    )
    # `employee_id` and `time_start` are here because they decide WHICH
    # attendance a line belongs to: changing one moves the line, and both the
    # attendance it left and the one it joined have to be recomputed.
    _ATTENDANCE_TRIGGER_FIELDS = frozenset(
        {"status", "duration", "manual_duration", "employee_id", "time_start"}
    )

    def _mark_to_recompute(self, attendances):
        # Marked AFTER the write or unlink, never before: both flush pending
        # computes on their way in, which would compute these fields against
        # the old rows and mark them clean again.
        for field_name in self._ATTENDANCE_DERIVED_FIELDS:
            self.env.add_to_compute(attendances._fields[field_name], attendances)

    def write(self, vals):
        if self._ATTENDANCE_TRIGGER_FIELDS.isdisjoint(vals):
            return super().write(vals)
        # A line that moves leaves one attendance and joins another; both are
        # wrong afterwards, and only the one it left is reachable beforehand.
        previously_linked = self._linked_attendances()
        res = super().write(vals)
        self._mark_to_recompute(previously_linked | self._linked_attendances())
        return res

    def unlink(self):
        orphaned = self._linked_attendances()
        res = super().unlink()
        self._mark_to_recompute(orphaned)
        return res
