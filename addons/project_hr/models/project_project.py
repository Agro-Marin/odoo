from odoo import api, fields, models
from odoo.tools import LazyTranslate

_lt = LazyTranslate(__name__)


class ProjectProject(models.Model):
    _name = "project.project"
    _inherit = ["mixin.hr", "project.project"]

    employee_id = fields.Many2one(
        "hr.employee",
        string="Project Manager",
        tracking=True,
        default=lambda self: self.env["hr.employee"].search(
            [
                ("user_id", "=", self.env.uid),
                ("company_id", "=", self.env.company.id),
            ],
            limit=1,
        ),
        falsy_value_label=_lt("👤 No Manager"),
    )

    user_id = fields.Many2one(
        "res.users",
        compute="_compute_user_id",
        store=True,
        readonly=True,
        string="Project Manager (User)",
        tracking=False,
        default=None,
    )

    @api.depends("employee_id.user_id")
    def _compute_user_id(self):
        for project in self:
            project.user_id = project.employee_id.user_id
