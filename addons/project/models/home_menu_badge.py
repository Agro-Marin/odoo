from odoo import api, models


class HomeMenuBadge(models.AbstractModel):
    _inherit = "home.menu.badge"

    @api.model
    def _get_badges(self) -> dict[str, int]:
        # The reader's own open tasks. `is_closed` rather than an enumeration
        # of the states that happen to be closed today, which is what the
        # Open Tasks filter reads.
        #
        # `project_id` set, because a task without one is a personal to-do and
        # belongs to the To-do tile, which counts them itself. project_todo
        # auto-installs and gives every internal user an onboarding to-do, so
        # without this clause every user in the database carries a Project
        # badge for work that is not in a project.
        return {
            **super()._get_badges(),
            **self._count_for(
                "project.menu_project_root",
                "project.task",
                [
                    ("is_closed", "=", False),
                    ("project_id", "!=", False),
                    ("user_ids", "in", self.env.uid),
                ],
            ),
        }
