from odoo import fields, models


class ReportProjectTaskUser(models.Model):
    """Extend task analysis report with employee_ids for search compatibility."""

    _inherit = "report.project.task.user"

    employee_ids = fields.Many2many(
        "hr.employee",
        related="task_id.employee_ids",
        string="Employees",
    )
