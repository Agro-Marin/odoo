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

            menus = self.env["ir.ui.menu"].browse(visible_menu_ids)
            self.env["ir.actions.act_window"].sudo().browse(
                [
                    int(menu["action"].split(",")[1])
                    for menu in menus.read(["action", "parent_path"])
                    if menu["action"]
                    and menu["action"].startswith("ir.actions.act_window,")
                ]
            ).filtered("res_model")

            def _menu_sort_key(menu_action: tuple) -> tuple:
                menu, action = menu_action
                return 1 if action.path else 0, -menu.id

            menu_sudo = max(
                (
                    (menu, action)
                    for menu in menus.sudo()
                    for action in (menu.action,)
                    if action
                    and action.type == "ir.actions.act_window"
                    and action.res_model == res_model
                    and all(
                        int(menu_id) in visible_menu_ids
                        for menu_id in menu.parent_path.split("/")
                        if menu_id
                    )
                ),
                key=_menu_sort_key,
                default=(None, None),
            )[0]
            return (
                int(menu_sudo.parent_path[: menu_sudo.parent_path.index("/")])
                if menu_sudo
                else None
            )
