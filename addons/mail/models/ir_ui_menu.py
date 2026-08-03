import contextlib

from odoo import api, models
from odoo.exceptions import AccessError


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    @api.model
    def _get_best_backend_root_menu_id_for_model(self, res_model):
        """Get the best menu root id for the given res_model and the access
        rights of the user.

        Looks for a menu root having a sub menu visible to the user with an
        action on ``res_model``. Ties are broken by favoring an action with a
        path (probably a "major" action), then the smallest menu id (probably
        the model's main module rather than a sub-one).

        :param str res_model: the model name for which we want to find the best
            menu root id
        :return: the best menu root id or None if not found
        :rtype: int | None
        """
        # a link to a record mailed to a user opens a page without menu, leaving
        # them no way to act on it
        with contextlib.suppress(AccessError):  # if no access to the menu, return None
            visible_menu_ids = self._visible_menu_ids()
            # Try first to get a menu root from the model implementation (take the less specialized i.e. the first one)
            menu_root_candidates = self.env[res_model]._get_backend_root_menu_ids()
            menu_root_id = next(
                (m_id for m_id in menu_root_candidates if m_id in visible_menu_ids),
                None,
            )
            if menu_root_id:
                return menu_root_id

            # No menu root could be found by interrogating the model so fall back to a simple heuristic
            # Prefetch menu fields and all menu's actions of type act_window
            menus = self.env["ir.ui.menu"].browse(visible_menu_ids)
            self.env["ir.actions.act_window"].sudo().browse(
                [
                    int(menu["action"].split(",")[1])
                    for menu in menus.read(["action", "parent_path"])
                    if menu["action"]
                    and menu["action"].startswith("ir.actions.act_window,")
                ]
            ).filtered("res_model")

            def _menu_sort_key(menu_action):
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
