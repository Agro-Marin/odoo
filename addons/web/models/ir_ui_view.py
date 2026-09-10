from typing import Any

from odoo import models
from odoo.tools import ormcache


class IrUiView(models.Model):
    _inherit = "ir.ui.view"

    @ormcache("self.env.lang")
    def get_view_info(self) -> dict[str, dict[str, Any]]:
        _view_info = self._get_view_info()
        return {
            type_: {
                "display_name": display_name,
                "icon": _view_info[type_]["icon"],
                "multi_record": _view_info[type_].get("multi_record", True),
            }
            for (type_, display_name) in self.fields_get(["type"], ["selection"])[
                "type"
            ]["selection"]
            if type_ != "qweb" and type_ in _view_info
        }

    def _get_view_info(self) -> dict[str, dict[str, Any]]:
        """What each view type declares about itself, keyed by type.

        ``icon`` and ``multi_record`` reach the client through
        :meth:`get_view_info`; ``date_range`` does not -- it says the arch's
        ``date_start``/``date_stop`` bound the records a listing shows, and
        the ``/json`` route reads it to filter by date.
        """
        return {
            "list": {"icon": "oi oi-view-list"},
            "form": {"icon": "fa-solid fa-address-card", "multi_record": False},
            "graph": {"icon": "fa-solid fa-chart-area"},
            "pivot": {"icon": "oi oi-view-pivot"},
            "kanban": {"icon": "oi oi-view-kanban"},
            "calendar": {"icon": "fa-solid fa-calendar-days", "date_range": True},
            "search": {"icon": "oi oi-search"},
        }

    def _view_type_has_date_range(self, view_type: str) -> bool:
        return bool(self._get_view_info().get(view_type, {}).get("date_range"))
