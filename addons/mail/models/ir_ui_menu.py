import contextlib

from odoo import api, models
from odoo.exceptions import AccessError


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    @api.model
    def _get_best_backend_root_menu_id_for_model(self, res_model: str) -> int | None:
        with contextlib.suppress(AccessError):
            visible_menu_ids = self._visible_menu_ids()
            menu_root_candidates = self.env[res_model]._get_backend_root_menu_ids()
            menu_root_id = next(
                (m_id for m_id in menu_root_candidates if m_id in visible_menu_ids),
                None,
            )
            if menu_root_id:
                return menu_root_id

            menus_data = (
                self.env["ir.ui.menu"]
                .browse(visible_menu_ids)
                .read(["action", "parent_path"])
            )
            action_id_by_menu_id = {
                menu["id"]: int(menu["action"].split(",")[1])
                for menu in menus_data
                if menu["action"]
                and menu["action"].startswith("ir.actions.act_window,")
            }
            actions = (
                self.env["ir.actions.act_window"]
                .sudo()
                .browse(list(set(action_id_by_menu_id.values())))
            )
            actions.fetch(["res_model", "path"])
            action_by_id = {action.id: action for action in actions}

            def _menu_sort_key(candidate: tuple) -> tuple:
                menu_id, _parent_path, action = candidate
                return 1 if action.path else 0, -menu_id

            _menu_id, parent_path, _action = max(
                (
                    (menu["id"], menu["parent_path"], action)
                    for menu in menus_data
                    if (
                        action := action_by_id.get(action_id_by_menu_id.get(menu["id"]))
                    )
                    and action.res_model == res_model
                    and all(
                        int(menu_id) in visible_menu_ids
                        for menu_id in menu["parent_path"].split("/")
                        if menu_id
                    )
                ),
                key=_menu_sort_key,
                default=(None, None, None),
            )
            return int(parent_path[: parent_path.index("/")]) if parent_path else None
