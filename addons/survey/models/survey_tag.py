from odoo import models


class SurveyTag(models.Model):
    _name = "survey.tag"
    _description = "Survey Tag"
    _inherit = ["mixin.tag"]
