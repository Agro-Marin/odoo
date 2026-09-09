from collections import defaultdict

from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        if self.env.context.get("salary_simulation"):
            return employees

        self.with_context(
            allowed_company_ids=employees.company_id.ids
        )._create_future_public_holidays_timesheets(employees)
        return employees

    def write(self, vals):
        if vals.get("active"):
            inactive_emp = self.filtered(lambda e: not e.active)
        result = super().write(vals)
        self_company = self.with_context(allowed_company_ids=self.company_id.ids)
        if "active" in vals:
            if vals.get("active"):
                inactive_emp = inactive_emp.with_env(self_company.env)
                inactive_emp._create_future_public_holidays_timesheets(inactive_emp)
            else:
                self_company._remove_future_public_holidays_timesheets()
        elif "resource_calendar_id" in vals:
            self_company._remove_future_public_holidays_timesheets()
            self_company._create_future_public_holidays_timesheets(self_company)
        return result

    def _remove_future_public_holidays_timesheets(self):
        future_timesheets = (
            self.env["account.analytic.line"]
            .sudo()
            .search(
                [
                    ("global_leave_id", "!=", False),
                    ("date", ">=", fields.Date.today()),
                    ("employee_id", "in", self.ids),
                ]
            )
        )
        future_timesheets.write({"global_leave_id": False})
        future_timesheets.unlink()

    def _create_future_public_holidays_timesheets(self, employees):
        lines_vals = []
        today = fields.Datetime.today()
        global_leaves_wo_calendar = defaultdict(
            lambda: self.env["resource.calendar.leaves"]
        )
        global_leaves_wo_calendar.update(
            dict(
                self.env["resource.calendar.leaves"]._read_group(
                    [
                        ("calendar_id", "=", False),
                        ("resource_id", "=", False),
                        ("date_from", ">=", today),
                    ],
                    groupby=["company_id"],
                    aggregates=["id:recordset"],
                )
            )
        )
        for employee in employees:
            if not employee.active:
                continue
            global_leaves = (
                employee.resource_calendar_id.global_leave_ids.filtered(
                    lambda l: l.date_from >= today
                )
                + global_leaves_wo_calendar[employee.company_id]
            )
            work_hours_data = global_leaves._work_time_per_day()
            for global_time_off in global_leaves:
                for index, (day_date, work_hours_count) in enumerate(
                    work_hours_data[employee.resource_calendar_id.id][
                        global_time_off.id
                    ]
                ):
                    lines_vals.append(
                        global_time_off._timesheet_prepare_line_values(
                            index,
                            employee,
                            work_hours_data[global_time_off.id],
                            day_date,
                            work_hours_count,
                        )
                    )
        return self.env["account.analytic.line"].sudo().create(lines_vals)
