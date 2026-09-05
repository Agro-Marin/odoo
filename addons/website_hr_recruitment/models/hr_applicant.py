from odoo import _, models
from odoo.exceptions import UserError


class HrApplicant(models.Model):
    _inherit = "hr.applicant"

    def website_form_input_filter(self, request, values):
        if values.get("job_id"):
            job = self.env["hr.job"].browse(values.get("job_id"))
            if not job.sudo().active:
                raise UserError(_("The job offer has been closed."))
        return values
