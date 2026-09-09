from odoo import api, models


class HomeMenuBadge(models.AbstractModel):
    _inherit = "home.menu.badge"

    @api.model
    def _get_badges(self) -> dict[str, int]:
        return {
            **super()._get_badges(),
            **self._count_for(
                "project_todo.menu_todo_todos",
                "project.task",
                [
                    ("is_closed", "=", False),
                    ("project_id", "=", False),
                    ("user_ids", "in", self.env.uid),
                ],
            ),
        }
