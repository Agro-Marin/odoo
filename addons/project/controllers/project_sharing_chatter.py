from werkzeug.exceptions import Forbidden

from odoo.http import request

from .portal import ProjectCustomerPortal
from odoo.addons.portal.controllers.portal_thread import PortalChatter


class ProjectSharingChatter(PortalChatter):
    def _check_project_access_and_get_token(
        self, project_id: int, res_model: str, res_id: int, token: str | None
    ) -> str:
        project_sudo = ProjectCustomerPortal._document_check_access(
            self, "project.project", project_id, token
        )
        can_access = (
            project_sudo
            and res_model == "project.task"
            and project_sudo.with_user(request.env.user)._check_project_sharing_access()
        )
        task = None
        if can_access:
            task = (
                request.env["project.task"]
                .sudo()
                .with_context(active_test=False)
                .search([("id", "=", res_id), ("project_id", "=", project_sudo.id)])
            )
        if not can_access or not task:
            raise Forbidden
        return task[task._mail_post_token_field]
