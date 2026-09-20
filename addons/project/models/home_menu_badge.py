from odoo import api, models

from ..tools import debug_log as dbg


class HomeMenuBadge(models.AbstractModel):
    _inherit = "home.menu.badge"

    @dbg.timed
    @api.model
    def _get_badges(self) -> dict[str, int]:
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
