from typing import Any, Self

from odoo import api, fields, models
from odoo.orm._typing import ValuesType


class ResGroupsPrivilege(models.Model):
    _name = "res.groups.privilege"
    _description = "Privileges"
    _order = "sequence, name, id"

    name = fields.Char(required=True, translate=True)
    description = fields.Text()
    # The default "No" is intended display text, not a sentinel: the user-form
    # group widget (web/.../user_groups/res_user_group_ids_field.js:90) uses it
    # as the label of the empty (`false`) option in this privilege's selection
    # dropdown, i.e. "no access for this privilege". As a plain Python default
    # string it is not run through translate=True; per-record values entered in
    # the UI are translatable.
    placeholder = fields.Char(
        default="No",
        help="Label shown for the empty option in the privilege selection field of the user form (e.g. 'No' access).",
    )
    sequence = fields.Integer(default=100)
    category_id = fields.Many2one("ir.module.category", string="Category", index=True)
    group_ids = fields.One2many("res.groups", "privilege_id", string="Groups")

    # Privilege metadata (name, description, placeholder, category, sequence) is
    # read into the cached `groups` registry family by
    # res.groups._get_view_group_hierarchy. The CRUD overrides below bust that
    # cache so the settings / user-form group widget never shows stale privilege
    # data. Privilege writes are rare and config-time, so the clear is cheap.

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
