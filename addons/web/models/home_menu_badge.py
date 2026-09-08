from typing import Any

from odoo import api, models


class HomeMenuBadge(models.AbstractModel):
    _name = "home.menu.badge"
    _description = "App Launcher Tile Counts"

    @api.model
    def get_badges(self) -> dict[str, int]:
        """{app xmlid: count}, for the current user, zeroes dropped."""
        return {
            xmlid: count for xmlid, count in self._get_badges().items() if count > 0
        }

    @api.model
    def _get_badges(self) -> dict[str, int]:
        return {}

    @api.model
    def _count_for(self, xmlid: str, model: str, domain: list[Any]) -> dict[str, int]:
        records = self.env.get(model)
        if records is None or not records.has_access("read"):
            return {}
        return {xmlid: records.search_count(domain)}
