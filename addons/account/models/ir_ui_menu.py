from odoo import models


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    def _get_account_readonly_menu_ids(self):
        return [
            "account.account_tag_menu",
            "account.menu_account_group",
        ]

    def _get_visible_menu_ids(self, debug=False):
        visible_ids = super()._get_visible_menu_ids(debug)
        if not self.env.user.has_group("account.group_account_readonly"):
            accounting_menus = self._get_account_readonly_menu_ids()
            hidden_menu_ids = {
                menu_id
                for ref_menu in accounting_menus
                if (menu_id := self.env["ir.model.data"]._xmlid_to_res_id(ref_menu))
            }
            return visible_ids - hidden_menu_ids
        return visible_ids
