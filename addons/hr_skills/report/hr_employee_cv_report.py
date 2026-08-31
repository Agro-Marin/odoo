from collections import defaultdict

from odoo import models


class ReportHr_SkillsReport_Employee_Cv(models.AbstractModel):
    _name = "report.hr_skills.report_employee_cv"
    _description = "Employee Resume"

    def _get_report_values(self, docids, data=None):
        show_others = (data or {}).get("show_others")
        employees = self.env["hr.employee"].browse(docids)

        resume_lines = {}
        for employee in employees:
            grouped = defaultdict(self.env["hr.resume.line"].browse)
            for line in employee.resume_line_ids:
                if not show_others and not line.line_type_id:
                    continue
                grouped[line.line_type_id] |= line
            resume_lines[employee] = {
                line_type.name or self.env._("Other"): lines
                for line_type, lines in grouped.items()
            }

        return {
            "doc_ids": docids,
            "doc_model": "hr.employee",
            "docs": employees,
            "resume_lines": resume_lines,
        }
