"""Junction model linking tasks, users, and personal triage buckets.

Each (task, user) pair has exactly one triage bucket entry; the unique
constraint at the database level enforces this.
"""

from odoo import fields, models


class ProjectTaskTriage(models.Model):
    """Per-user triage assignment for a task.

    Represents the personal triage bucket that a specific user has placed a
    task into. Invisible to other users.
    """

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
