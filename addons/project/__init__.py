from . import controllers
from . import models
from . import report
from . import wizard

from odoo.libs.sql import make_identifier
from odoo.db.schema import create_index


def _check_exists_collaborators_for_project_sharing(env) -> None:
    collaborator = env["project.collaborator"].search([], limit=1)
    if collaborator:
        env["project.collaborator"]._toggle_project_sharing_portal_rules(True)


def _project_post_init(env) -> None:
    _check_exists_collaborators_for_project_sharing(env)

    project_task_step_field_id = (
        env["ir.model.fields"]._get_ids("project.task").get("step_id")
    )
    create_index(
        env.cr,
        make_identifier(
            "mail_tracking_value_mail_message_id_old_value_integer_task_step"
        ),
        env["mail.tracking.value"]._table,
        ["mail_message_id", "old_value_integer"],
        where=f"field_id={project_task_step_field_id}",
    )

    env["account.analytic.plan"].search([])._sync_plan_column("project.project")


def _project_uninstall_hook(env) -> None:
    env["project.share.wizard"].search(
        [("partner_ids", "!=", False)]
    ).partner_ids = False
