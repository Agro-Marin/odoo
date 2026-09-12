from werkzeug.exceptions import Forbidden

from odoo.http import request

from ..tools import debug_log as dbg
from .portal import ProjectCustomerPortal
from odoo.addons.portal.controllers.portal_thread import PortalChatter


class ProjectSharingChatter(PortalChatter):
    def _get_task_post_token(
        self, project_id: int, res_model: str, res_id: int, token: str | None
    ) -> str:
        project_sudo = ProjectCustomerPortal._document_check_access(
            self, "project.project", project_id, token
        )
        can_access = (
            project_sudo
            and res_model == "project.task"
            and project_sudo.with_user(
                request.env.user
            )._is_project_sharing_accessible()
        )
        task = None
        if can_access:
            task = (
                request.env["project.task"]
                .sudo()
                .with_context(active_test=False)
                .search([("id", "=", res_id), ("project_id", "=", project_sudo.id)])
            )
        dbg.logic.debug(
            "[portal:sharing_chatter] project %s %s/%s uid=%s: can_access=%s task=%s",
            project_id,
            res_model,
            res_id,
            request.env.uid,
            bool(can_access),
            task and task.id,
        )
        if not can_access or not task:
            raise Forbidden
        return task[task._mail_post_token_field]
