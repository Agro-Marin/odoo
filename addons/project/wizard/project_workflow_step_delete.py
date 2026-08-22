"""Wizard to archive or delete workflow steps from a project."""

from typing import Any

from odoo import _, api, fields, models


class ProjectWorkflowStepDeleteWizard(models.TransientModel):
    """Confirmation wizard for archiving/deleting workflow steps."""

    _name = "project.workflow.step.delete.wizard"
    _description = "Workflow Step Delete Wizard"

    project_ids = fields.Many2many(
        "project.project",
        domain="['|', ('active', '=', False), ('active', '=', True)]",
        string="Projects",
        ondelete="cascade",
        export_string_translation=False,
    )
    step_ids = fields.Many2many(
        "project.workflow.step",
        string="Steps To Delete",
        ondelete="cascade",
        export_string_translation=False,
    )
    tasks_count = fields.Integer(
        "Number of Tasks",
        compute="_compute_tasks_count",
        export_string_translation=False,
    )
    steps_active = fields.Boolean(
        compute="_compute_steps_active", export_string_translation=False
    )

    @api.depends("step_ids")
    def _compute_tasks_count(self) -> None:
        # One GROUP BY over every wizard's step_ids rather than a
        # COUNT(*) per wizard, which `test_lint E8507` counts as a query
        # inside a loop. `step_id` is a Many2one, so each record falls in
        # exactly one group and summing a wizard's groups cannot double-count.
        counts = dict(
            self.env["project.task"]
            .with_context(active_test=False)
            ._read_group(
                [("step_id", "in", self.step_ids.ids)],
                ["step_id"],
                ["__count"],
            )
        )
        for wizard in self:
            wizard.tasks_count = sum(
                counts.get(record, 0) for record in wizard.step_ids
            )

    @api.depends("step_ids")
    def _compute_steps_active(self) -> None:
        for wizard in self:
            wizard.steps_active = all(wizard.step_ids.mapped("active"))

    def action_archive(self) -> dict[str, Any]:
        if len(self.project_ids) <= 1:
            return self.action_confirm()

        return {
            "name": _("Confirmation"),
            "view_mode": "form",
            "res_model": "project.workflow.step.delete.wizard",
            "views": [
                (
                    self.env.ref(
                        "project.view_project_workflow_step_delete_confirmation_wizard"
                    ).id,
                    "form",
                )
            ],
            "type": "ir.actions.act_window",
            "res_id": self.id,
            "target": "new",
            "context": self.env.context,
        }

    def action_unarchive_task(self) -> None:
        inactive_tasks = (
            self.env["project.task"]
            .with_context(active_test=False)
            .search([("active", "=", False), ("step_id", "in", self.step_ids.ids)])
        )
        inactive_tasks.action_unarchive()

    def action_confirm(self) -> dict[str, Any]:
        tasks = (
            self.with_context(active_test=False)
            .env["project.task"]
            .search([("step_id", "in", self.step_ids.ids)])
        )
        tasks.write({"active": False})
        self.step_ids.write({"active": False})
        return self._get_action()

    def action_unlink(self) -> dict[str, Any]:
        self.step_ids.unlink()
        return self._get_action()

    def _get_action(self) -> dict[str, Any]:
        return {
            "type": "ir.actions.act_window_close",
            "infos": {
                "success": True,
            },
        }
