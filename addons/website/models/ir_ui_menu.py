# Part of Odoo. See LICENSE file for full copyright and licensing details.

import copy

from odoo import api, models, tools
from odoo.http import request


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    @api.model
    @tools.ormcache(
        "self.env.uid", "self.env.lang", 'self.env.context.get("force_action")'
    )
    def load_menus_root(self):
        root_menus = super().load_menus_root()
        if self.env.context.get("force_action"):
            # `super().load_menus_root()` is itself ormcached and returns a
            # shared mutable dict; mutating it in place would leak forced actions
            # into every later (non-force) webclient menu load process-wide.
            # Copy before mutating. (`debug` is intentionally not part of the
            # cache key: the forced value is "model,id", which does not vary by
            # debug.)
            root_menus = copy.deepcopy(root_menus)
            web_menus = self.load_web_menus(request.session.debug if request else False)
            for menu in root_menus["children"]:
                # Force the action. Guard the lookup: a root menu id is not
                # guaranteed to be present in web_menus (KeyError otherwise).
                web_menu = web_menus.get(menu["id"])
                if (
                    not menu["action"]
                    and web_menu
                    and web_menu["actionModel"]
                    and web_menu["actionID"]
                ):
                    menu["action"] = f"{web_menu['actionModel']},{web_menu['actionID']}"

        return root_menus
