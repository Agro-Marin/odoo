from odoo import fields, models


class ProjectPhase(models.Model):
    """Add SMS template capability to project phases."""

    _inherit = 'project.phase'

    sms_template_id = fields.Many2one(
        'sms.template',
        string="SMS Template",
        domain=[('model', '=', 'project.project')],
        help="If set, an SMS Text Message will be automatically sent to the "
             "customer when the project reaches this phase.",
    )
