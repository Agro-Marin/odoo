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
                "stock.menu_stock_root",
                "stock.picking",
                [
                    ("state", "in", ("assigned", "waiting", "confirmed")),
                    "|",
                    ("has_deadline_issue", "=", True),
                    ("date_category", "in", ["before", "yesterday"]),
                ],
            ),
        }
