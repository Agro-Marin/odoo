from odoo import api, models


class ResGroups(models.Model):
    _inherit = "res.groups"

    @api.model
    def _activate_group_account_secured(self):
        group_account_secured = self.env.ref(
            "account.group_account_secured", raise_if_not_found=False
        )
        if not group_account_secured:
            return
        groups_with_access = [
            "account.group_account_readonly",
            "account.group_account_invoice",
        ]
        for group_name in groups_with_access:
            group = self.env.ref(group_name, raise_if_not_found=False)
            if group:
                group.sudo()._add_implied_group(group_account_secured)
