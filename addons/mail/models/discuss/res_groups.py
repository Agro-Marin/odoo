from typing import Literal

from odoo import models
from odoo.api import ValuesType


class ResGroups(models.Model):
    _inherit = "res.groups"

    def write(self, vals: ValuesType) -> Literal[True]:
        res = super().write(vals)
        if vals.get("user_ids"):
            self.env["discuss.channel"].search(
                [("group_ids", "in", self.all_implied_ids._ids)]
            )._subscribe_users_automatically()
        return res
