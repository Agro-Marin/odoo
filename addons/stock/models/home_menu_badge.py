from odoo import api, models


class HomeMenuBadge(models.AbstractModel):
    _inherit = "home.menu.badge"

    @api.model
    def _get_badges(self) -> dict[str, int]:
        # Verbatim the `late` filter of the transfers search view: deadline
        # exceeded, or scheduled before today, and not yet done. Copied rather
        # than reworded so the tile and the list it opens cannot disagree
        # about what is late.
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
