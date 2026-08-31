from odoo import models


class HrApplicantCategory(models.Model):
    _name = "hr.applicant.category"
    _description = "Category of applicant"
    _inherit = ["mixin.tag"]
