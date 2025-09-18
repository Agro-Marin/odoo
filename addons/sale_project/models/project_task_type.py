from odoo import api, fields, models


class ProjectWorkflowStep(models.Model):
    """Add rating visibility based on billable projects."""

    _inherit = 'project.workflow.step'

    show_rating_active = fields.Boolean(compute='_compute_show_rating_active', export_string_translation=False)

    @api.depends('project_ids.allow_billable')
    def _compute_show_rating_active(self):
        for step in self:
            step.show_rating_active = any(step.project_ids.mapped('allow_billable'))

    @api.onchange('project_ids')
    def _onchange_project_ids(self):
        if not any(self.project_ids.mapped('allow_billable')):
            self.rating_active = False
