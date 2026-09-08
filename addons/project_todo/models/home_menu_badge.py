from odoo import api, models


class HomeMenuBadge(models.AbstractModel):
    _inherit = "home.menu.badge"

    @api.model
    def _get_badges(self) -> dict[str, int]:
        # A to-do is a task with no project, which is what this app's own
        # menus filter on. `project` excludes exactly these, so the two tiles
        # partition the reader's open tasks instead of double-counting them.
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
