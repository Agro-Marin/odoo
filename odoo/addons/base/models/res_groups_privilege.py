from typing import Any, Self

from odoo import api, fields, models
from odoo.api import ValuesType


class ResGroupsPrivilege(models.Model):
    _name = "res.groups.privilege"
    _description = "Privileges"
    _order = "sequence, name, id"

    name = fields.Char(required=True, translate=True)
    description = fields.Text()
    placeholder = fields.Char(
        default="No",
        help="Label shown for the empty option in the privilege selection field of the user form (e.g. 'No' access).",
    )
    sequence = fields.Integer(default=100)
    category_id = fields.Many2one("ir.module.category", string="Category", index=True)
    group_ids = fields.One2many("res.groups", "privilege_id", string="Groups")

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        records = super().create(vals_list)
        self.env.registry.clear_cache("groups")
        return records

    def write(self, vals: dict[str, Any]) -> bool:
        res = super().write(vals)
        self.env.registry.clear_cache("groups")
        return res

    def unlink(self) -> bool:
        res = super().unlink()
        self.env.registry.clear_cache("groups")
        return res
