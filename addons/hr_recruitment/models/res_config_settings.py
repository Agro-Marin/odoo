from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    module_website_hr_recruitment = fields.Boolean(string="Online Posting")
    module_hr_recruitment_survey = fields.Boolean(string="Interview Forms")
    module_extract_hr_recruitment = fields.Boolean(
        string="Read an applicant's CV"
    )
