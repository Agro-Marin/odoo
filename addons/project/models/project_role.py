from random import randint

from odoo import fields, models


class ProjectRole(models.Model):
    _name = "project.role"
    _description = "Project Role"
    _inherit = ["project.pm.mixin"]

    def _get_default_color(self) -> int:
        return randint(1, 11)

    active = fields.Boolean(default=True)
    name = fields.Char(required=True, translate=True)
    color = fields.Integer(default=_get_default_color)
    sequence = fields.Integer(export_string_translation=False)
