"""Project lifecycle phases (PMI terminology alignment).

PMI/PMBOK defines a *phase* as "a collection of logically related project
activities that culminates in the completion of one or more deliverables" —
exactly what Odoo's project stages represent at the project level.
"""

from typing import Any

from odoo import _, fields, models
from odoo.exceptions import UserError


class ProjectPhase(models.Model):
    """A lifecycle phase of a project (e.g. Planning, Execution, Closing).

    Phases are shared across projects within the same company. A project
    occupies exactly one phase at any given time. Folded phases are shown
    collapsed in Kanban/List views and are treated as closed.
    """

    _name = "project.phase"
    _description = "Project Phase"
    _inherit = ["project.pm.mixin"]
    _order = "sequence, id"

    active = fields.Boolean(default=True, export_string_translation=False)
    sequence = fields.Integer(default=50, export_string_translation=False)
    name = fields.Char(required=True, translate=True)
    mail_template_id = fields.Many2one(
        "mail.template",
        string="Email Template",
        domain=[("model", "=", "project.project")],
        help="Email sent automatically when a project enters this phase.",
    )
    fold = fields.Boolean(
        "Folded",
        help=(
            "Folded phases are shown collapsed in Kanban and List views. "
            "Projects in a folded phase are considered closed."
        ),
    )
    company_id = fields.Many2one("res.company", string="Company")
    color = fields.Integer(string="Color", export_string_translation=False)

    def unlink_wizard(self, stage_view: bool = False) -> dict[str, Any]:
        """Open the delete/archive confirmation wizard for these phases."""
        wizard = self.env["project.phase.delete.wizard"].create({"phase_ids": self.ids})
        context = dict(self.env.context, stage_view=stage_view)
        return {
            "name": _("Delete Phase"),
            "view_mode": "form",
            "res_model": "project.phase.delete.wizard",
            "views": [
                (
                    self.env.ref("project.view_project_phase_delete_wizard").id,
                    "form",
                )
            ],
            "type": "ir.actions.act_window",
            "res_id": wizard.id,
            "target": "new",
            "context": context,
        }

    def write(self, vals: dict) -> bool:
        """Guard company switches when projects are already assigned to this phase."""
        if vals.get("company_id"):
            project = self.env["project.project"].search(
                [
                    "&",
                    ("phase_id", "in", self.ids),
                    ("company_id", "!=", vals["company_id"]),
                ],
                limit=1,
            )
            if project:
                company = self.env["res.company"].browse(vals["company_id"])
                raise UserError(
                    _(
                        "You cannot switch this phase to %(company_name)s because it "
                        "currently includes projects linked to %(project_company_name)s.",
                        company_name=company.name,
                        project_company_name=project.company_id.name or _("no company"),
                    )
                )
        if "active" in vals and not vals["active"]:
            self.env["project.project"].search([("phase_id", "in", self.ids)]).write(
                {"active": False}
            )
        return super().write(vals)
