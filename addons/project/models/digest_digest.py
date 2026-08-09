from typing import Any

from odoo import _, fields, models
from odoo.exceptions import AccessError

from .project_task import CLOSED_STATES


class DigestDigest(models.Model):
    _inherit = "digest.digest"

    kpi_project_task_opened = fields.Boolean("Open Tasks")
    kpi_project_task_opened_value = fields.Integer(
        compute="_compute_project_task_opened_value",
        export_string_translation=False,
    )

    def _compute_project_task_opened_value(self) -> None:
        if not self.env.user.has_group("project.group_project_user"):
            raise AccessError(
                _("Do not have access, skip this data for user's digest email")
            )

        # "Open" is `state`, not the folded-ness of the board column the task
        # happens to sit in. This was the last place in the module keying off
        # `step_id.fold` for a closure decision, and it disagreed with the app in
        # both directions: a done task parked in a non-folded column counted as
        # open, and an in-progress task dragged into a folded one did not. See
        # ProjectTask._compute_date_closed for why `state` is the single closure
        # signal; this matches ProjectProject._compute_open_task_count.
        self._calculate_company_based_kpi(
            "project.task",
            "kpi_project_task_opened_value",
            additional_domain=[
                ("state", "not in", list(CLOSED_STATES)),
                ("project_id", "!=", False),
            ],
        )

    def _compute_kpis_actions(self, company: Any, user: Any) -> dict:
        res = super()._compute_kpis_actions(company, user)
        res["kpi_project_task_opened"] = (
            "project.open_view_project_all?menu_id=%s"
            % self.env.ref("project.menu_project_root").id
        )
        return res
