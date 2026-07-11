"""Wizard to archive or delete project phases."""

from ast import literal_eval
from typing import Any

from odoo import api, fields, models


class ProjectPhaseDeleteWizard(models.TransientModel):
    """Confirmation wizard for archiving/deleting project phases."""

    _name = "project.phase.delete.wizard"
    _description = "Project Phase Delete Wizard"

    phase_ids = fields.Many2many(
        "project.phase",
        string="Phases To Delete",
        ondelete="cascade",
        context={"active_test": False},
        export_string_translation=False,
    )
    projects_count = fields.Integer(
        "Number of Projects",
        compute="_compute_projects_count",
        export_string_translation=False,
    )
    phases_active = fields.Boolean(
        compute="_compute_phases_active", export_string_translation=False
    )

    def _compute_projects_count(self) -> None:
        for wizard in self:
            wizard.projects_count = (
                self.with_context(active_test=False)
                .env["project.project"]
                .search_count([("phase_id", "in", wizard.phase_ids.ids)])
            )

    @api.depends("phase_ids")
    def _compute_phases_active(self) -> None:
        for wizard in self:
            wizard.phases_active = all(wizard.phase_ids.mapped("active"))

    def action_archive(self) -> dict[str, Any]:
        projects = (
            self.with_context(active_test=False)
            .env["project.project"]
            .search([("phase_id", "in", self.phase_ids.ids)])
        )
        projects.write({"active": False})
        self.phase_ids.write({"active": False})
        return self._get_action()

    def action_unarchive_project(self) -> None:
        inactive_projects = (
            self.env["project.project"]
            .with_context(active_test=False)
            .search([("active", "=", False), ("phase_id", "in", self.phase_ids.ids)])
        )
        inactive_projects.action_unarchive()

    def action_unlink(self) -> dict[str, Any]:
        self.phase_ids.unlink()
        return self._get_action()

    def _get_action(self) -> dict[str, Any]:
        action = (
            self.env["ir.actions.actions"]._for_xml_id(
                "project.project_phase_configure"
            )
            if self.env.context.get("stage_view")
            else self.env["ir.actions.actions"]._for_xml_id(
                "project.open_view_project_all_group_phase"
            )
        )

        context = action.get("context", "{}")
        context = context.replace("uid", str(self.env.uid))
        context = dict(literal_eval(context), active_test=True)
        action["context"] = context
        action["target"] = "main"
        return action
