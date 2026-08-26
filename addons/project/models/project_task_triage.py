from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProjectTaskTriage(models.Model):
    _name = "project.task.triage"
    _description = "Task Triage Assignment"
    _rec_name = "triage_id"

    task_id = fields.Many2one(
        "project.task",
        required=True,
        ondelete="cascade",
        index=True,
        export_string_translation=False,
    )
    user_id = fields.Many2one(
        "res.users",
        required=True,
        ondelete="cascade",
        index=True,
        export_string_translation=False,
    )
    triage_id = fields.Many2one(
        "project.triage",
        domain="[('user_id', '=', user_id)]",
        ondelete="set null",
        export_string_translation=False,
    )

    _project_task_triage_unique = models.Constraint(
        "UNIQUE (task_id, user_id)",
        "A task can only have one triage bucket per user.",
    )

    @api.constrains("user_id", "triage_id")
    def _check_triage_owner(self) -> None:
        for rec in self:
            if rec.triage_id and rec.triage_id.user_id != rec.user_id:
                raise ValidationError(
                    self.env._(
                        "A personal triage bucket must belong to the same user "
                        "as the task-triage entry."
                    )
                )
